# Odoo Tool Auto-Discovery: Comprehensive Guidance for Coding Agent

**Purpose:** Generate a complete `tools/registry.py` and extract constraint metadata at three knowledge levels (KL-1 / KL-2 / KL-3) from an Odoo Docker instance — even when no demo/business data is populated.

**Audience:** Local coding agent (Cursor / Claude Code / Copilot) executing against the project codebase.

---

## 0. Prerequisites & Assumptions

### 0.1 What Must Be True Before You Start

| Condition | How to Verify | If Not Met |
|-----------|--------------|------------|
| Docker container running | `docker ps \| grep odoo` | `docker compose up -d` |
| Odoo web accessible | `curl -s http://localhost:8069/web/login \| head -5` | Check port mapping in `docker-compose.yml` |
| PostgreSQL container running | `docker ps \| grep postgres` | Start the db service |
| **At least one database exists** | See §0.2 below | Create one via §0.2 |
| Odoo modules are **installed** (not just present on disk) | See §0.3 below | Install via §0.3 |

### 0.2 Database Initialization (Critical — Empty Data Is Fine)

The Odoo shell command `odoo shell -d <db_name>` **requires a database to exist with the base module installed**. Demo data is NOT required. An empty-but-initialized database is sufficient for schema introspection.

**Check if a database exists:**

```bash
# From the host
docker exec -it <postgres_container> psql -U odoo -l
# Look for your database name in the output
```

**If NO database exists, create one:**

```bash
# Option A: Via Odoo CLI (preferred — initializes base module automatically)
docker exec -it <odoo_container> odoo -d halluci_action_db -i base --stop-after-init --without-demo=all

# Option B: Via the web UI at http://localhost:8069/web/database/manager
# Click "Create Database", fill in name, set master password, UNCHECK "Load demonstration data"
```

**Critical:** The `--without-demo=all` flag ensures no demo data is loaded. This is fine — we only need the **schema** (model definitions, field definitions, constraint decorators), not actual records.

### 0.3 Ensuring Target Modules Are Installed

Tool discovery only finds models from **installed** modules. Modules that are merely present in the addons path but not installed will be invisible to `env[...]`.

```bash
# Install ALL modules you plan to evaluate (comma-separated, no spaces)
docker exec -it <odoo_container> odoo -d halluci_action_db \
  -i sale,point_of_sale,crm,stock,hr,hr_holidays,hr_attendance,helpdesk,purchase,account,project,mrp,website,mail \
  --stop-after-init --without-demo=all
```

**How to discover what modules are available on disk (before installing):**

```bash
docker exec -it <odoo_container> find /usr/lib/python3/dist-packages/odoo/addons -maxdepth 1 -type d | sort
# Also check custom addons path:
docker exec -it <odoo_container> find /mnt/extra-addons -maxdepth 1 -type d 2>/dev/null | sort
```

**Verify installation succeeded:**

```bash
docker exec -it <odoo_container> odoo shell -d halluci_action_db <<'EOF'
installed = env['ir.module.module'].search([('state', '=', 'installed')])
for m in installed:
    print(f"{m.name:30s} {m.shortdesc}")
EOF
```

---

## 1. Phase 1 — Auto-Discover All Models and Their Public Methods

### 1.1 Script: `discover_models.py`

Create this script. It will be executed **inside the Odoo shell context**.

```python
#!/usr/bin/env python3
"""
Odoo Model & Method Discovery Script.
Run via: docker exec -it <odoo_container> odoo shell -d halluci_action_db < discover_models.py

Outputs JSON to stdout. Redirect to file:
  docker exec -it <odoo_container> odoo shell -d halluci_action_db < discover_models.py > discovery_raw.json 2>/dev/null
"""
import json
import sys

results = []

# 1. Get all installed models
all_models = env['ir.model'].search_read(
    [('transient', '=', False)],  # Exclude wizard/transient models
    ['model', 'name', 'info', 'state']
)

for model_rec in all_models:
    model_name = model_rec['model']

    # Skip internal/base models that are not tool-relevant
    SKIP_PREFIXES = (
        'ir.', 'base.', 'bus.', 'res.config', 'web_',
        'report.', 'mail.', 'fetchmail.', 'digest.',
        'base_import.', 'publisher_warranty.',
    )
    if any(model_name.startswith(p) for p in SKIP_PREFIXES):
        continue

    try:
        Model = env[model_name]
    except KeyError:
        continue

    # 2. Extract fields (these become tool parameters)
    try:
        fields = Model.fields_get(attributes=[
            'string', 'type', 'required', 'readonly',
            'help', 'selection', 'relation', 'domain'
        ])
    except Exception:
        fields = {}

    # 3. Extract public methods (candidates for tool actions)
    public_methods = []
    for attr_name in dir(Model):
        if attr_name.startswith('_'):
            continue
        attr = getattr(type(Model), attr_name, None)
        if callable(attr):
            # Capture docstring if present
            doc = getattr(attr, '__doc__', '') or ''
            public_methods.append({
                'name': attr_name,
                'docstring': doc[:500]  # Truncate long docstrings
            })

    # 4. Extract constraints (critical for KL levels)
    constraints_sql = []
    constraints_python = []

    # SQL constraints from _sql_constraints
    sql_c = getattr(type(Model), '_sql_constraints', [])
    for sc in sql_c:
        if isinstance(sc, (list, tuple)) and len(sc) >= 3:
            constraints_sql.append({
                'name': sc[0],
                'sql': sc[1],
                'message': sc[2]
            })

    # Python constraints from @api.constrains decorators
    for attr_name in dir(type(Model)):
        attr = getattr(type(Model), attr_name, None)
        if callable(attr) and hasattr(attr, '_constrains'):
            doc = getattr(attr, '__doc__', '') or ''
            constraints_python.append({
                'method': attr_name,
                'fields': list(attr._constrains) if hasattr(attr, '_constrains') else [],
                'docstring': doc[:500]
            })

    results.append({
        'model': model_name,
        'display_name': model_rec['name'],
        'description': model_rec.get('info', ''),
        'fields': fields,
        'public_methods': public_methods,
        'sql_constraints': constraints_sql,
        'python_constraints': constraints_python,
    })

# Output as JSON
print(json.dumps(results, indent=2, default=str))
env.cr.rollback()  # Don't commit anything
sys.exit()
```

### 1.2 Execution Instructions

```bash
# Step 1: Copy the script into the container
docker cp discover_models.py <odoo_container>:/tmp/discover_models.py

# Step 2: Execute inside the Odoo shell
# IMPORTANT: Redirect stderr to avoid Odoo startup noise polluting JSON output
docker exec -i <odoo_container> odoo shell -d halluci_action_db \
  < /tmp/discover_models.py \
  > discovery_raw.json \
  2>/dev/null

# Step 3: Validate the output is valid JSON
python3 -c "import json; data=json.load(open('discovery_raw.json')); print(f'Discovered {len(data)} models')"
```

### 1.3 Known Pitfalls

| Issue | Symptom | Fix |
|-------|---------|-----|
| Odoo shell prints banner text into stdout | JSON parse error | Use `2>/dev/null` on stderr; if banner still bleeds into stdout, pipe through `sed -n '/^\[/,$p'` or `python3 -c "import sys,json; [... find first '[' ...]"` to strip preamble |
| Module not installed | Model missing from output | Re-run §0.3 with the missing module added to `-i` |
| `KeyError: '<model>'` | Model registered in ir.model but class not loaded | The module may have been partially uninstalled; ignore and continue |
| `env.cr` in broken state | Subsequent queries fail | Always `env.cr.rollback()` before `sys.exit()` |
| Enterprise-only modules (e.g., `helpdesk`) | Module not found | Use Community alternatives or install Enterprise addons separately |

---

## 2. Phase 2 — Extract Constraint Information for KL-1 / KL-2 / KL-3

### 2.1 Knowledge Level Definitions

| Level | What the Agent Knows | Constraints Included? | Source |
|-------|---------------------|----------------------|--------|
| **KL-1** (Full Knowledge) | Complete tool schema + ALL constraints + business rules | Yes — full constraint text in tool descriptions | `_sql_constraints`, `@api.constrains`, docstrings, field `help` attributes |
| **KL-2** (Partial Knowledge) | Tool schema + field types/required flags, but **constraints stripped** from descriptions | No — agent must infer constraints from field metadata only | Field `required`, `readonly`, `type`, `selection` options |
| **KL-3** (Minimal Knowledge) | Tool name + one-line description only; no parameter schema | No | Model `display_name` only |

### 2.2 Script: `extract_constraints.py`

This script processes the `discovery_raw.json` from Phase 1 and produces three separate tool description files.

```python
#!/usr/bin/env python3
"""
Transforms discovery_raw.json into three KL-level tool registries.
Run on your HOST machine (not inside Docker).

Usage:
  python3 extract_constraints.py discovery_raw.json --output-dir tools/
"""
import json
import argparse
from pathlib import Path

# ─── Domain classification heuristics ───
DOMAIN_MAP = {
    'sale.order': 'retail', 'sale.order.line': 'retail',
    'pos.order': 'retail', 'pos.order.line': 'retail',
    'purchase.order': 'procurement', 'purchase.order.line': 'procurement',
    'crm.lead': 'crm', 'crm.team': 'crm',
    'res.partner': 'crm',
    'stock.quant': 'inventory', 'stock.picking': 'inventory',
    'stock.move': 'inventory', 'stock.warehouse': 'inventory',
    'stock.location': 'inventory',
    'hr.employee': 'hr', 'hr.leave': 'hr',
    'hr.attendance': 'hr', 'hr.department': 'hr',
    'helpdesk.ticket': 'helpdesk',
    'project.project': 'project', 'project.task': 'project',
    'account.move': 'accounting', 'account.move.line': 'accounting',
    'account.payment': 'accounting',
    'mrp.production': 'manufacturing', 'mrp.bom': 'manufacturing',
}

def classify_domain(model_name: str) -> str:
    """Assign a domain label. Fall back to the first dotted segment."""
    if model_name in DOMAIN_MAP:
        return DOMAIN_MAP[model_name]
    prefix = model_name.split('.')[0]
    FALLBACK = {
        'sale': 'retail', 'pos': 'retail', 'crm': 'crm',
        'stock': 'inventory', 'hr': 'hr', 'helpdesk': 'helpdesk',
        'project': 'project', 'account': 'accounting',
        'purchase': 'procurement', 'mrp': 'manufacturing',
    }
    return FALLBACK.get(prefix, 'general')


def build_tool_actions(model: dict) -> list:
    """
    Convert a model's public methods into tool-action definitions.

    Heuristic: We select methods that look like user-facing operations.
    Standard CRUD (create/read/write/unlink) is always included.
    Domain-specific methods are identified by prefix patterns.
    """
    ACTION_PREFIXES = (
        'action_', 'button_', 'process_', 'do_', 'send_',
        'confirm', 'cancel', 'approve', 'reject', 'validate',
        'assign', 'close', 'escalate', 'refuse', 'reset',
    )
    CRUD_METHODS = ['create', 'read', 'write', 'unlink', 'search_read']

    actions = []
    seen = set()
    for method in model.get('public_methods', []):
        name = method['name']
        if name in seen:
            continue
        is_crud = name in CRUD_METHODS
        is_action = any(name.startswith(p) for p in ACTION_PREFIXES)
        if is_crud or is_action:
            seen.add(name)
            actions.append({
                'method': name,
                'docstring': method.get('docstring', ''),
                'is_crud': is_crud,
            })
    return actions


def format_constraints_kl1(model: dict) -> str:
    """Full constraint text for KL-1."""
    lines = []
    for sc in model.get('sql_constraints', []):
        lines.append(f"[SQL] {sc['name']}: {sc['message']} ({sc['sql']})")
    for pc in model.get('python_constraints', []):
        fields_str = ', '.join(pc.get('fields', []))
        doc = pc.get('docstring', '').strip()
        desc = doc if doc else '(no docstring)'
        lines.append(f"[Python @api.constrains({fields_str})] {pc['method']}: {desc}")

    # Also include field-level constraints
    for fname, fmeta in model.get('fields', {}).items():
        notes = []
        if fmeta.get('required'):
            notes.append('REQUIRED')
        if fmeta.get('readonly'):
            notes.append('read-only')
        if fmeta.get('help'):
            notes.append(f"help: {fmeta['help']}")
        if fmeta.get('domain'):
            notes.append(f"domain filter: {fmeta['domain']}")
        if notes:
            lines.append(f"[Field:{fname}] {', '.join(notes)}")
    return '\n'.join(lines)


def build_kl1_tool(model: dict, actions: list) -> dict:
    """KL-1: Full schema + all constraints in description."""
    params = {}
    for fname, fmeta in model.get('fields', {}).items():
        param = {
            'type': fmeta.get('type', 'unknown'),
            'description': fmeta.get('string', fname),
            'required': fmeta.get('required', False),
        }
        if fmeta.get('selection'):
            param['enum'] = [s[0] for s in fmeta['selection']]
        if fmeta.get('help'):
            param['description'] += f" — {fmeta['help']}"
        if fmeta.get('relation'):
            param['relation'] = fmeta['relation']
        params[fname] = param

    constraint_text = format_constraints_kl1(model)
    description = model.get('description', '') or model.get('display_name', '')
    if constraint_text:
        description += f"\n\nCONSTRAINTS:\n{constraint_text}"

    return {
        'name': model['model'],
        'display_name': model.get('display_name', ''),
        'domain': classify_domain(model['model']),
        'description': description,
        'actions': [a['method'] for a in actions],
        'parameters': params,
    }


def build_kl2_tool(model: dict, actions: list) -> dict:
    """KL-2: Schema with types/required but NO constraint descriptions."""
    params = {}
    for fname, fmeta in model.get('fields', {}).items():
        param = {
            'type': fmeta.get('type', 'unknown'),
            'description': fmeta.get('string', fname),
            'required': fmeta.get('required', False),
        }
        if fmeta.get('selection'):
            param['enum'] = [s[0] for s in fmeta['selection']]
        # NOTE: intentionally omit 'help', 'domain', constraint info
        params[fname] = param

    return {
        'name': model['model'],
        'display_name': model.get('display_name', ''),
        'domain': classify_domain(model['model']),
        'description': model.get('display_name', ''),  # Minimal description
        'actions': [a['method'] for a in actions],
        'parameters': params,
    }


def build_kl3_tool(model: dict, actions: list) -> dict:
    """KL-3: Name + one-line description only."""
    return {
        'name': model['model'],
        'display_name': model.get('display_name', ''),
        'domain': classify_domain(model['model']),
        'description': model.get('display_name', ''),
        'actions': [a['method'] for a in actions],
        # No parameters exposed
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input_json', help='Path to discovery_raw.json')
    parser.add_argument('--output-dir', default='tools/', help='Output directory')
    args = parser.parse_args()

    data = json.load(open(args.input_json))
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    kl1_tools, kl2_tools, kl3_tools = [], [], []
    constraint_audit = []  # Separate file for human review

    for model in data:
        actions = build_tool_actions(model)
        if not actions:
            continue  # Skip models with no actionable methods

        kl1_tools.append(build_kl1_tool(model, actions))
        kl2_tools.append(build_kl2_tool(model, actions))
        kl3_tools.append(build_kl3_tool(model, actions))

        # Audit record
        constraint_audit.append({
            'model': model['model'],
            'domain': classify_domain(model['model']),
            'sql_constraints': model.get('sql_constraints', []),
            'python_constraints': model.get('python_constraints', []),
            'required_fields': [
                fname for fname, fmeta in model.get('fields', {}).items()
                if fmeta.get('required')
            ],
            'readonly_fields': [
                fname for fname, fmeta in model.get('fields', {}).items()
                if fmeta.get('readonly')
            ],
        })

    # Write outputs
    with open(out / 'registry_kl1.json', 'w') as f:
        json.dump(kl1_tools, f, indent=2, default=str)
    with open(out / 'registry_kl2.json', 'w') as f:
        json.dump(kl2_tools, f, indent=2, default=str)
    with open(out / 'registry_kl3.json', 'w') as f:
        json.dump(kl3_tools, f, indent=2, default=str)
    with open(out / 'constraint_audit.json', 'w') as f:
        json.dump(constraint_audit, f, indent=2, default=str)

    # Summary
    domains = {}
    for t in kl1_tools:
        domains.setdefault(t['domain'], []).append(t['name'])

    print(f"\n{'='*60}")
    print(f"Tool Discovery Complete")
    print(f"{'='*60}")
    print(f"Total models with actions: {len(kl1_tools)}")
    print(f"Domains found: {len(domains)}")
    for domain, models in sorted(domains.items()):
        print(f"  {domain:20s} → {len(models)} models")
    print(f"\nOutput files:")
    print(f"  {out}/registry_kl1.json  (full constraints)")
    print(f"  {out}/registry_kl2.json  (schema only)")
    print(f"  {out}/registry_kl3.json  (minimal)")
    print(f"  {out}/constraint_audit.json  (human review)")


if __name__ == '__main__':
    main()
```

### 2.3 Generating the Final `tools/registry.py`

After the JSON files are generated, transform them into the Python registry your gateway expects:

```python
#!/usr/bin/env python3
"""
generate_registry.py — Convert registry_kl1.json → tools/registry.py

Usage:
  python3 generate_registry.py tools/registry_kl1.json --kl 1
"""
import json
import argparse

TEMPLATE = '''"""
Auto-generated Odoo tool registry — Knowledge Level {kl}
Generated from Odoo introspection. Do NOT edit manually.
Regenerate via: python3 generate_registry.py registry_kl{kl}.json --kl {kl}
"""

TOOLS = {tools_repr}

# Domain → model mapping for TOOL_TABLE_MAP in gateway.py
DOMAIN_INDEX = {domain_repr}

# For gateway.py: tool_name → list of tables to snapshot
TOOL_TABLE_MAP = {table_map_repr}
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input_json')
    parser.add_argument('--kl', type=int, default=1)
    parser.add_argument('--output', default='tools/registry.py')
    args = parser.parse_args()

    tools = json.load(open(args.input_json))

    # Build TOOL_TABLE_MAP: each action → the Odoo model (table) it touches
    table_map = {}
    domain_index = {}
    for tool in tools:
        model = tool['name']
        table_name = model.replace('.', '_')  # Odoo table naming convention
        domain_index.setdefault(tool.get('domain', 'general'), []).append(model)
        for action in tool.get('actions', []):
            key = f"{model}.{action}"
            # Primary table is always the model itself;
            # add related tables for relational fields
            related_tables = {table_name}
            for pname, pmeta in tool.get('parameters', {}).items():
                if pmeta.get('relation'):
                    related_tables.add(pmeta['relation'].replace('.', '_'))
            table_map[key] = sorted(related_tables)

    output = TEMPLATE.format(
        kl=args.kl,
        tools_repr=json.dumps(tools, indent=2, default=str),
        domain_repr=json.dumps(domain_index, indent=2),
        table_map_repr=json.dumps(table_map, indent=2),
    )

    with open(args.output, 'w') as f:
        f.write(output)
    print(f"Written {args.output} with {len(tools)} tools, {len(table_map)} actions")

if __name__ == '__main__':
    main()
```

---

## 3. Phase 3 — Deep Constraint Extraction from Source Code

The shell-based discovery (Phase 1–2) captures `_sql_constraints` and `@api.constrains` decorators. However, many business rules are encoded in **method bodies** (e.g., `if order.date_order < fields.Datetime.now() - timedelta(days=30): raise UserError(...)`). These are invisible to reflection.

### 3.1 Script: `extract_source_constraints.py`

This script runs **inside the Docker container** and performs AST analysis on Python source files.

```python
#!/usr/bin/env python3
"""
Static analysis of Odoo module source code to extract:
  - raise UserError / ValidationError patterns (implicit constraints)
  - @api.constrains decorators
  - _sql_constraints
  - Field definitions with domain filters

Run inside Docker:
  docker exec -it <odoo_container> python3 /tmp/extract_source_constraints.py > source_constraints.json

Scans:
  /usr/lib/python3/dist-packages/odoo/addons/
  /mnt/extra-addons/
"""
import ast
import json
import os
import sys

ADDONS_PATHS = [
    '/usr/lib/python3/dist-packages/odoo/addons',
    '/opt/odoo/addons',         # Some Docker images use this
    '/mnt/extra-addons',        # Custom addons volume
]

# Only scan modules we care about
TARGET_MODULES = None  # Set to a list like ['sale', 'crm', ...] to filter, or None for all

results = []

def extract_raise_patterns(node, filepath, module_name):
    """Find all `raise UserError(...)` and `raise ValidationError(...)` patterns."""
    patterns = []
    for child in ast.walk(node):
        if isinstance(child, ast.Raise) and child.exc:
            exc = child.exc
            # Handle raise UserError("message") and raise ValidationError("message")
            if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
                if exc.func.id in ('UserError', 'ValidationError'):
                    # Try to extract the message string
                    msg = ''
                    if exc.args and isinstance(exc.args[0], ast.Constant):
                        msg = str(exc.args[0].value)
                    elif exc.args and isinstance(exc.args[0], ast.Call):
                        # Common pattern: raise UserError(_("message"))
                        inner = exc.args[0]
                        if inner.args and isinstance(inner.args[0], ast.Constant):
                            msg = str(inner.args[0].value)
                    patterns.append({
                        'type': exc.func.id,
                        'message': msg[:300],
                        'file': filepath,
                        'line': child.lineno,
                    })
            # Handle raise from attribute: e.g., raise exceptions.ValidationError
            elif isinstance(exc, ast.Call) and isinstance(exc.func, ast.Attribute):
                attr_name = exc.func.attr
                if attr_name in ('UserError', 'ValidationError'):
                    msg = ''
                    if exc.args and isinstance(exc.args[0], ast.Constant):
                        msg = str(exc.args[0].value)
                    elif exc.args and isinstance(exc.args[0], ast.Call):
                        inner = exc.args[0]
                        if inner.args and isinstance(inner.args[0], ast.Constant):
                            msg = str(inner.args[0].value)
                    patterns.append({
                        'type': attr_name,
                        'message': msg[:300],
                        'file': filepath,
                        'line': child.lineno,
                    })
    return patterns


def scan_module(module_path, module_name):
    """Scan all .py files in a module directory."""
    module_results = {
        'module': module_name,
        'raise_patterns': [],
        'api_constrains': [],
        'sql_constraints_source': [],
    }

    models_dir = os.path.join(module_path, 'models')
    if not os.path.isdir(models_dir):
        models_dir = module_path  # Some modules put models at top level

    for root, dirs, files in os.walk(module_path):
        for fname in files:
            if not fname.endswith('.py'):
                continue
            filepath = os.path.join(root, fname)
            relative_path = os.path.relpath(filepath, module_path)
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    source = f.read()
                tree = ast.parse(source)
            except (SyntaxError, UnicodeDecodeError):
                continue

            # Extract raise patterns
            raises = extract_raise_patterns(tree, relative_path, module_name)
            module_results['raise_patterns'].extend(raises)

            # Find @api.constrains decorators via AST
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    for dec in node.decorator_list:
                        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                            if dec.func.attr == 'constrains':
                                fields = [
                                    a.value if isinstance(a, ast.Constant) else str(a)
                                    for a in dec.args
                                ]
                                # Get the docstring
                                doc = ast.get_docstring(node) or ''
                                module_results['api_constrains'].append({
                                    'method': node.name,
                                    'fields': fields,
                                    'docstring': doc[:300],
                                    'file': relative_path,
                                    'line': node.lineno,
                                })

            # Find _sql_constraints assignments
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == '_sql_constraints':
                            # Attempt to evaluate the literal
                            try:
                                val = ast.literal_eval(node.value)
                                for item in val:
                                    if isinstance(item, (list, tuple)) and len(item) >= 3:
                                        module_results['sql_constraints_source'].append({
                                            'name': item[0],
                                            'sql': item[1],
                                            'message': item[2],
                                            'file': relative_path,
                                            'line': node.lineno,
                                        })
                            except (ValueError, TypeError):
                                pass

    return module_results


for addons_path in ADDONS_PATHS:
    if not os.path.isdir(addons_path):
        continue
    for entry in sorted(os.listdir(addons_path)):
        module_path = os.path.join(addons_path, entry)
        if not os.path.isdir(module_path):
            continue
        if TARGET_MODULES and entry not in TARGET_MODULES:
            continue
        if entry.startswith('.') or entry == '__pycache__':
            continue

        result = scan_module(module_path, entry)
        if result['raise_patterns'] or result['api_constrains'] or result['sql_constraints_source']:
            results.append(result)

print(json.dumps(results, indent=2, ensure_ascii=False))
```

### 3.2 Merging Source Constraints into KL-1

After running the source extraction, merge the `raise UserError(...)` messages into your KL-1 tool descriptions. These represent **implicit constraints** — business rules enforced in code but not declared in metadata.

```python
# merge_constraints.py (run on host)
import json

registry = json.load(open('tools/registry_kl1.json'))
source = json.load(open('source_constraints.json'))

# Build module → raise patterns index
module_raises = {}
for mod in source:
    module_raises[mod['module']] = mod['raise_patterns']

for tool in registry:
    model_name = tool['name']
    # Odoo module name is typically the first segment: 'sale.order' → 'sale'
    module_guess = model_name.split('.')[0]
    raises = module_raises.get(module_guess, [])
    if raises:
        constraint_lines = [
            f"[BusinessRule] {r['message']} (from {r['file']}:{r['line']})"
            for r in raises if r['message']
        ]
        tool['description'] += '\n\nIMPLICIT BUSINESS RULES:\n' + '\n'.join(constraint_lines)

with open('tools/registry_kl1_enriched.json', 'w') as f:
    json.dump(registry, f, indent=2, default=str)
```

---

## 4. Validation Checklist

Run these checks before considering the registry complete:

### 4.1 Coverage Check

```python
# validate_coverage.py
import json

kl1 = json.load(open('tools/registry_kl1.json'))
audit = json.load(open('tools/constraint_audit.json'))

# Check 1: Every domain has at least 2 models
domains = {}
for t in kl1:
    domains.setdefault(t['domain'], []).append(t['name'])

print("=== Domain Coverage ===")
for d, models in sorted(domains.items()):
    status = "OK" if len(models) >= 2 else "WARNING: single model"
    print(f"  {d:20s}: {len(models):3d} models  [{status}]")

# Check 2: Every model has at least 1 non-CRUD action
no_actions = [t['name'] for t in kl1 if len(t.get('actions', [])) <= 5]
if no_actions:
    print(f"\n WARNING: {len(no_actions)} models have only CRUD actions:")
    for m in no_actions[:10]:
        print(f"    {m}")

# Check 3: KL-1 has constraints, KL-2 doesn't
kl2 = json.load(open('tools/registry_kl2.json'))
kl1_with_constraints = sum(1 for t in kl1 if 'CONSTRAINTS' in t.get('description', ''))
kl2_with_constraints = sum(1 for t in kl2 if 'CONSTRAINTS' in t.get('description', ''))
print(f"\n=== Constraint Separation ===")
print(f"  KL-1 tools with constraints: {kl1_with_constraints}")
print(f"  KL-2 tools with constraints: {kl2_with_constraints}  (should be 0)")
assert kl2_with_constraints == 0, "KL-2 should have NO constraint text!"

# Check 4: Constraint audit has entries
models_with_constraints = sum(
    1 for a in audit
    if a['sql_constraints'] or a['python_constraints']
)
print(f"\n=== Constraint Audit ===")
print(f"  Models with declared constraints: {models_with_constraints} / {len(audit)}")
```

### 4.2 Mapping to TOOL_TABLE_MAP

Verify that every tool action maps to at least one database table, and that the table exists in PostgreSQL:

```bash
# Generate table list from registry
python3 -c "
import json
tools = json.load(open('tools/registry_kl1.json'))
tables = set()
for t in tools:
    tables.add(t['name'].replace('.', '_'))
for table in sorted(tables):
    print(table)
" > expected_tables.txt

# Compare against actual Odoo tables
docker exec -it <postgres_container> psql -U odoo -d halluci_action_db -t -c "
  SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;
" > actual_tables.txt

# Diff
comm -23 <(sort expected_tables.txt) <(sort actual_tables.txt | sed 's/^ *//')
# Any lines printed here are models without corresponding tables (may indicate
# modules not installed, or abstract models that don't create tables)
```

---

## 5. Complete Execution Order (Copy-Paste Checklist)

```bash
# ──────────────────────────────────────────────
# STEP 0: Environment verification
# ──────────────────────────────────────────────
docker ps | grep -E "odoo|postgres"                    # Both must be running
docker exec -it <postgres_container> psql -U odoo -l   # Check DB exists

# ──────────────────────────────────────────────
# STEP 1: Initialize DB if needed (safe to skip if DB exists)
# ──────────────────────────────────────────────
docker exec -it <odoo_container> odoo -d halluci_action_db \
  -i base --stop-after-init --without-demo=all

# ──────────────────────────────────────────────
# STEP 2: Install ALL target modules
# Adjust this list based on `find ... addons` output
# ──────────────────────────────────────────────
docker exec -it <odoo_container> odoo -d halluci_action_db \
  -i sale,point_of_sale,crm,stock,hr,hr_holidays,hr_attendance,helpdesk,purchase,account,project,mrp \
  --stop-after-init --without-demo=all

# ──────────────────────────────────────────────
# STEP 3: Run model/method discovery
# ──────────────────────────────────────────────
docker cp discover_models.py <odoo_container>:/tmp/
docker exec -i <odoo_container> odoo shell -d halluci_action_db \
  < /tmp/discover_models.py > discovery_raw.json 2>/dev/null

# Validate
python3 -c "import json; d=json.load(open('discovery_raw.json')); print(f'{len(d)} models')"

# ──────────────────────────────────────────────
# STEP 4: Run source-code constraint extraction
# ──────────────────────────────────────────────
docker cp extract_source_constraints.py <odoo_container>:/tmp/
docker exec -i <odoo_container> python3 /tmp/extract_source_constraints.py \
  > source_constraints.json 2>/dev/null

# ──────────────────────────────────────────────
# STEP 5: Generate KL-1/2/3 registries
# ──────────────────────────────────────────────
python3 extract_constraints.py discovery_raw.json --output-dir tools/

# ──────────────────────────────────────────────
# STEP 6: Enrich KL-1 with source constraints
# ──────────────────────────────────────────────
python3 merge_constraints.py

# ──────────────────────────────────────────────
# STEP 7: Generate final registry.py
# ──────────────────────────────────────────────
python3 generate_registry.py tools/registry_kl1_enriched.json --kl 1 --output tools/registry_kl1.py
python3 generate_registry.py tools/registry_kl2.json --kl 2 --output tools/registry_kl2.py
python3 generate_registry.py tools/registry_kl3.json --kl 3 --output tools/registry_kl3.py

# ──────────────────────────────────────────────
# STEP 8: Validate
# ──────────────────────────────────────────────
python3 validate_coverage.py
```

---

## 6. Edge Cases & Troubleshooting

| Scenario | Symptom | Resolution |
|----------|---------|------------|
| `helpdesk` module not found | Enterprise-only module | Either install Odoo Enterprise, or define helpdesk tools manually in registry as a stub domain |
| `odoo shell` hangs | Waiting for user input | Pipe script via `< script.py` (not interactive mode); ensure script ends with `sys.exit()` |
| JSON output contains Odoo banner lines | `[2025-...] INFO ...` lines before JSON | Redirect stderr: `2>/dev/null`; if banner still in stdout, post-process to strip non-JSON preamble |
| Module installed but no public methods found | All methods start with `_` | These are private Odoo methods; for tool purposes, wrap CRUD ops (`create`, `write`, `search_read`, `unlink`) as the tool actions |
| `@api.constrains` not captured by reflection | Some decorators are consumed at class creation | Use Phase 3 (AST analysis) as the authoritative constraint source — it reads source code directly |
| `_sql_constraints` empty for a model | Model uses Python-only validation | This is normal; rely on `raise UserError`/`ValidationError` patterns from Phase 3 |
| Database exists but modules show `uninstalled` | DB was created without `-i` | Run Step 2 again — `-i` is idempotent for already-installed modules |

---

## 7. Output File Summary

| File | Purpose | Used By |
|------|---------|---------|
| `discovery_raw.json` | Raw introspection dump | Input to all subsequent scripts |
| `source_constraints.json` | AST-extracted business rules | Enriches KL-1 |
| `tools/registry_kl1.json` | Full schema + all constraints | Agent evaluation at KL-1 |
| `tools/registry_kl2.json` | Schema only, no constraints | Agent evaluation at KL-2 |
| `tools/registry_kl3.json` | Name + description only | Agent evaluation at KL-3 |
| `tools/registry_kl1_enriched.json` | KL-1 + implicit business rules | Final KL-1 source of truth |
| `tools/registry_kl{1,2,3}.py` | Python module for `gateway.py` | Runtime tool dispatch |
| `tools/constraint_audit.json` | Human-reviewable constraint list | Manual validation & paper writing |
