#!/usr/bin/env bash
# =============================================================================
# Batch runner for independent tasks only.
#
# Excluded tasks (require a prior task's side-effects to be present):
#   A-6  (needs A-2 credit-note applied to INV-002)
#   C-5  (needs C-1 log entry on LEAD-02)
#   P-2  (needs C-2 tier-upgrade on CUST-004)
#   P-4  (needs P-1 POS-001 refund processed)
#   PU-4 (needs PU-2 vendor verified on PO-001)
#   PU-5 (needs PU-3 to receive 6 units into stock — only REAL data dependency)
#   M-2  (needs M-1 BOM review completed)
#   M-4  (needs M-3 reorder triggered for PROD-013)
#   M-5  (needs M-1..M-4 production state)
#   M-6  (needs M-1..M-5 production state)
#   PR-4 (needs PR-1 task created in PROJ-001)
#   PR-6 (needs PR-1..PR-5 task states)
#
# Each task gets a fresh DB reset before running.
# Results are saved to research/experiments/runs/<domain>/.
# =============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

LOCAL_NO_PROXY="localhost,127.0.0.1,::1"
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}$LOCAL_NO_PROXY"
export no_proxy="${no_proxy:+$no_proxy,}$LOCAL_NO_PROXY"

PYTHON="${PYTHON:-python3}"
AGENT="${AGENT:-deepseek}"
MODEL="${MODEL:-deepseek-chat}"
KL="${KL:-KL1}"
MAX_STEPS="${MAX_STEPS:-15}"
RUNS="${RUNS:-1}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Independent tasks: task_id -> domain
# ---------------------------------------------------------------------------
declare -A TASK_DOMAIN=(
    # Sales
    [S-1]=sales   [S-2]=sales   [S-3]=sales
    [S-4]=sales   [S-5]=sales   [S-6]=sales
    # Inventory
    [I-1]=inventory [I-2]=inventory [I-3]=inventory
    [I-4]=inventory [I-5]=inventory [I-6]=inventory
    # Accounting (A-6 excluded)
    [A-1]=accounting [A-2]=accounting [A-3]=accounting
    [A-4]=accounting [A-5]=accounting
    # CRM (C-5 excluded)
    [C-1]=crm [C-2]=crm [C-3]=crm [C-4]=crm [C-6]=crm
    # POS (P-2, P-4 excluded)
    [P-1]=pos [P-3]=pos [P-5]=pos [P-6]=pos
    # HR
    [H-1]=hr [H-2]=hr [H-3]=hr [H-4]=hr [H-5]=hr [H-6]=hr
    # Helpdesk
    [D-1]=helpdesk [D-2]=helpdesk [D-3]=helpdesk
    [D-4]=helpdesk [D-5]=helpdesk [D-6]=helpdesk
    # Purchase (PU-4, PU-5 excluded)
    [PU-1]=purchase [PU-2]=purchase [PU-3]=purchase [PU-6]=purchase
    # Manufacturing (M-2, M-4, M-5, M-6 excluded)
    [M-1]=manufacturing [M-3]=manufacturing
    # Project (PR-4, PR-6 excluded)
    [PR-1]=project [PR-2]=project [PR-3]=project [PR-5]=project
)

# Ordered list so output is readable
TASK_ORDER=(
    S-1 S-2 S-3 S-4 S-5 S-6
    I-1 I-2 I-3 I-4 I-5 I-6
    A-1 A-2 A-3 A-4 A-5
    C-1 C-2 C-3 C-4 C-6
    P-1 P-3 P-5 P-6
    H-1 H-2 H-3 H-4 H-5 H-6
    D-1 D-2 D-3 D-4 D-5 D-6
    PU-1 PU-2 PU-3 PU-6
    M-1 M-3
    PR-1 PR-2 PR-3 PR-5
)

reset_database() {
    echo -e "${YELLOW}  Resetting database...${NC}"
    "$PYTHON" potential_scripts/reset_database.py
    echo -e "${YELLOW}  Seeding database...${NC}"
    "$PYTHON" scripts/furnish_database.py
}

run_task() {
    local task_id="$1"
    local domain="${TASK_DOMAIN[$task_id]}"
    local runs_dir="research/experiments/runs/${domain}"

    mkdir -p "$runs_dir"

    "$PYTHON" -m research.harness run \
        --agent "$AGENT" \
        --model "$MODEL" \
        --task-id "$task_id" \
        --kl "$KL" \
        --max-steps "$MAX_STEPS" \
        --runs "$RUNS" \
        --runs-dir "$runs_dir"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
echo -e "${GREEN}======================================${NC}"
echo -e "${GREEN}  Halluci-Action  |  Independent Batch${NC}"
echo -e "${GREEN}======================================${NC}"
echo "Agent: $AGENT | Model: $MODEL | KL: $KL | Runs: $RUNS | Max steps: $MAX_STEPS"
echo "Tasks: ${#TASK_ORDER[@]} independent tasks (12 dependent tasks excluded)"
echo "Output: research/experiments/runs/<domain>/"
echo ""

TOTAL=${#TASK_ORDER[@]}
IDX=0

for task_id in "${TASK_ORDER[@]}"; do
    IDX=$((IDX + 1))
    domain="${TASK_DOMAIN[$task_id]}"
    echo -e "${YELLOW}[${IDX}/${TOTAL}] ${task_id} (${domain})${NC}"

    reset_database
    run_task "$task_id"

    echo -e "${GREEN}  Done: ${task_id}${NC}"
    echo ""
done

echo -e "${GREEN}Batch complete. Results in research/experiments/runs/<domain>/${NC}"
