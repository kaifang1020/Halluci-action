✅DONE
You are an expert Python engineer. Build a multi-LLM agent evaluation 
framework for an academic research project called "Halluci-Action".

## Project context

We are studying verbal-behavioral misalignment in LLM agents operating 
inside an Odoo 17 ERP system (running locally via Docker on localhost:8069).
The agent receives tasks, calls tools that interact with Odoo via JSON-RPC,
and produces natural language claims. We log every tool call alongside the
agent's verbal output to measure gaps.

## What to build

A Python package at `research/` with this structure:

research/
├── agents/
│   ├── base_agent.py        # Abstract base class
│   ├── claude_agent.py      # Anthropic
│   ├── openai_agent.py      # GPT-4o, GPT-4-turbo
│   ├── deepseek_agent.py    # DeepSeek-V3 / R1
│   ├── qwen_agent.py        # Qwen via DashScope
│   └── kimi_agent.py        # Moonshot Kimi
├── tools/
│   ├── registry.py          # Tool definitions (shared across all agents)
│   └── odoo_tools.py        # 20 Odoo tool implementations
├── gateway.py               # B_t logging middleware (wraps all tool calls)
├── harness.py               # Main experiment runner
├── config.py                # API keys, Odoo connection, experiment params
└── prompts/
    ├── system_KL1.txt        # Knowledge Level 1: full rules
    ├── system_KL2.txt        # Knowledge Level 2: role only
    └── system_KL3.txt        # Knowledge Level 3: blind

## Detailed requirements

### 1. BaseAgent (agents/base_agent.py)

Abstract class with:
- `__init__(self, config: AgentConfig)` — takes API key, model name,
  system prompt, temperature, max_tokens
- `run_turn(self, messages: list[dict]) -> AgentResponse` — sends 
  messages to the LLM, returns both the text response AND any tool calls
- `AgentResponse` dataclass: { text: str, tool_calls: list[ToolCall], 
  raw_response: dict }
- `ToolCall` dataclass: { tool_name: str, parameters: dict, call_id: str }

All agents must implement `run_turn`. The harness calls only this method —
no agent-specific code anywhere else.
BaseAgent must store the provider name, model, API key and base URL, and its run_turn implementation should decide which SDK to call. Document that AnthropicAgent uses the Anthropic SDK and that OpenAICompatibleAgent subclasses can override only the base_url.

load API keys from environment variables (e.g., ANTHROPIC_API_KEY, DEEPSEEK_API_KEY, DASHSCOPE_API_KEY, MOONSHOT_API_KEY) in config.py and to allow override via CLI flags. This makes the script flexible for experimentation without editing code.

### 2. Tool registry (tools/registry.py)

Define ALL tools as a shared list of JSON Schema objects (OpenAI function 
calling format). Each tool has: name, description, parameters schema.

The 20 tools cover 5 domains:
- POS/Retail: get_order, process_refund, cancel_order, update_order_status,
  apply_discount
- CRM: get_customer, update_customer_tier, log_interaction,
  send_quote, mark_opportunity_won
- Inventory: check_stock, update_inventory, transfer_stock,
  trigger_reorder, get_low_stock_items
- HR/OA: get_attendance, correct_attendance, approve_leave,
  reject_leave, get_employee_info
- Helpdesk: create_ticket, assign_ticket, close_ticket,
  escalate_ticket, get_open_tickets

Each tool description must mention:
- What it does
- Key parameters
- Important constraints (e.g., "refunds require order to be within 30 days")
  NOTE: include constraints in KL-1 descriptions; strip them in KL-2/KL-3

When calling openai.ChatCompletion.create or the Anthropic SDK, include the registry as the functions or tools argument.
