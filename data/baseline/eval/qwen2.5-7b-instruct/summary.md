# Baseline (provider=ollama, model=qwen2.5:7b-instruct, T=0.3)

Seeds: **11**  |  errors: **0**  |  tokens: in=24721, out=3189

| Seed | Mode | First tool | ToolsValid | THOUGHT | SELF-CHECK | task_id | tokens in/out |
|------|------|------------|------------|---------|------------|---------|---------------|
| eval_01_agent | agent | plan_write | ✓ | ✓ | ✓ | ✓ | 2365/212 |
| eval_02_agent | agent | plan_write | ✓ | ✗ | ✗ | ✓ | 1898/215 |
| eval_03_agent | agent | — | ✓ | ✓ | ✓ | ✗ | 2379/471 |
| eval_04_agent | agent | plan_write | ✓ | ✓ | ✓ | ✓ | 2356/314 |
| eval_05_agent | agent | step_read | ✓ | ✓ | ✓ | ✓ | 2397/109 |
| eval_06_agent | agent | plan_write | ✓ | ✓ | ✓ | ✓ | 2365/270 |
| eval_07_agent_question | agent_question | plan_write | ✓ | ✓ | ✓ | ✓ | 2351/422 |
| eval_08_plain | plain | — | ✓ | ✗ | ✗ | ✗ | 1474/213 |
| eval_09_agent | agent | plan_write | ✓ | ✓ | ✓ | ✓ | 2352/275 |
| eval_10_agent_question | agent_question | plan_write | ✓ | ✓ | ✓ | ✓ | 2379/199 |
| eval_11_agent | agent | plan_write | ✓ | ✓ | ✓ | ✓ | 2405/489 |
