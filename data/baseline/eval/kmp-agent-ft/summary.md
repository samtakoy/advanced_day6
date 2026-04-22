# Baseline (provider=ollama, model=kmp-agent-ft, T=0.3)

Seeds: **11**  |  errors: **0**  |  tokens: in=24721, out=3597

| Seed | Mode | First tool | ToolsValid | THOUGHT | SELF-CHECK | task_id | tokens in/out |
|------|------|------------|------------|---------|------------|---------|---------------|
| eval_01_agent | agent | plan_write | ✓ | ✓ | ✓ | ✓ | 2365/300 |
| eval_02_agent | agent | — | ✓ | ✓ | ✓ | ✗ | 1898/331 |
| eval_03_agent | agent | — | ✓ | ✓ | ✓ | ✗ | 2379/323 |
| eval_04_agent | agent | plan_write | ✓ | ✓ | ✓ | ✓ | 2356/426 |
| eval_05_agent | agent | plan_write | ✓ | ✓ | ✓ | ✓ | 2397/324 |
| eval_06_agent | agent | step_read | ✓ | ✓ | ✓ | ✓ | 2365/97 |
| eval_07_agent_question | agent_question | — | ✓ | ✓ | ✓ | ✗ | 2351/132 |
| eval_08_plain | plain | — | ✓ | ✗ | ✗ | ✗ | 1474/637 |
| eval_09_agent | agent | plan_write | ✓ | ✓ | ✓ | ✓ | 2352/341 |
| eval_10_agent_question | agent_question | plan_write | ✓ | ✓ | ✓ | ✓ | 2379/490 |
| eval_11_agent | agent | — | ✓ | ✓ | ✓ | ✗ | 2405/196 |
