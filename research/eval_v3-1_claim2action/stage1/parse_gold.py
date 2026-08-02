from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GoldClaim:
    claim_id: str
    span: str
    type: str
    requires_validation: bool
    validation_scope: str


@dataclass
class GoldStep:
    step_id: int
    source: str
    claims: list[GoldClaim] = field(default_factory=list)


@dataclass
class GoldAnnotation:
    traj_id: str
    steps: list[GoldStep] = field(default_factory=list)


def parse_gold_annotation(path: Path) -> GoldAnnotation:
    text = path.read_text(encoding="utf-8")
    traj_id = path.stem

    annotation = GoldAnnotation(traj_id=traj_id)

    # Split on "## Step N" boundaries
    parts = re.split(r'\n## Step (\d+)\n', text)
    # parts[0] = header, then alternating: step_num_str, step_content

    i = 1
    while i + 1 < len(parts):
        step_id = int(parts[i])
        content = parts[i + 1]

        source_match = re.search(
            r'### Source\n(.*?)(?=\n### Stage 1 Claims|$)', content, re.DOTALL
        )
        source = source_match.group(1).strip() if source_match else ""

        claims: list[GoldClaim] = []
        claims_match = re.search(r'### Stage 1 Claims\n(.*?)$', content, re.DOTALL)

        if claims_match:
            claims_text = claims_match.group(1)
            claim_parts = re.split(r'\n#### ([^\n]+)\n', claims_text)
            # claim_parts[0] = preamble, then alternating: claim_id, claim_body

            j = 1
            while j + 1 < len(claim_parts):
                claim_id = claim_parts[j].strip()
                body = claim_parts[j + 1]

                span_match = re.search(r'Span:\s*`(.*)`', body)
                if not span_match:
                    j += 2
                    continue
                span = span_match.group(1)

                type_match = re.search(r'\nType:\s*(\S+)', body)
                claim_type = type_match.group(1) if type_match else ""

                req_match = re.search(r'Requires validation:\s*(\S+)', body)
                requires_validation = (
                    req_match.group(1).lower() == "yes" if req_match else False
                )

                scope_match = re.search(r'Validation scope:\s*(.+)', body)
                validation_scope = scope_match.group(1).strip() if scope_match else "—"

                claims.append(
                    GoldClaim(
                        claim_id=claim_id,
                        span=span,
                        type=claim_type,
                        requires_validation=requires_validation,
                        validation_scope=validation_scope,
                    )
                )
                j += 2

        # Skip steps annotated as having no claims
        annotation.steps.append(
            GoldStep(step_id=step_id, source=source, claims=claims)
        )
        i += 2

    return annotation
