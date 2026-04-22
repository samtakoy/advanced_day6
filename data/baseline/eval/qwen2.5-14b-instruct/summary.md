# Baseline (provider=ollama, model=qwen2.5:14b-instruct, T=0.3)

Seeds: **11**  |  errors: **0**  |  tokens: in=24721, out=3464

| Seed | Mode | First tool | ToolsValid | THOUGHT | SELF-CHECK | task_id | tokens in/out |
|------|------|------------|------------|---------|------------|---------|---------------|
| eval_01_agent | agent | read_file | ✓ | ✓ | ✓ | ✗ | 2365/220 |
| eval_02_agent | agent | list_dir | ✓ | ✗ | ✗ | ✗ | 1898/117 |
| eval_03_agent | agent | plan_write | ✓ | ✗ | ✗ | ✓ | 2379/356 |
| eval_04_agent | agent | read_file | ✓ | ✓ | ✓ | ✗ | 2356/146 |
| eval_05_agent | agent | plan_write | ✓ | ✗ | ✗ | ✓ | 2397/268 |
| eval_06_agent | agent | read_file | ✓ | ✗ | ✗ | ✗ | 2365/101 |
| eval_07_agent_question | agent_question | plan_write | ✓ | ✗ | ✗ | ✓ | 2351/204 |
| eval_08_plain | plain | — | ✓ | ✗ | ✗ | ✗ | 1474/831 |
| eval_09_agent | agent | plan_write | ✓ | ✗ | ✗ | ✓ | 2352/504 |
| eval_10_agent_question | agent_question | plan_write | ✓ | ✗ | ✗ | ✓ | 2379/460 |
| eval_11_agent | agent | list_dir | ✓ | ✓ | ✓ | ✗ | 2405/257 |
