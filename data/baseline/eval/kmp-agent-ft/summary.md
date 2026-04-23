# Baseline (provider=ollama, model=kmp-agent-ft, T=0.3)

Seeds: **11**  |  errors: **0**  |  tokens: in=16870, out=4416

| Seed | Mode | First tool | ToolsValid | THOUGHT | SELF-CHECK | task_id | tokens in/out |
|------|------|------------|------------|---------|------------|---------|---------------|
| eval_01_agent | agent | read_file | ✓ | ✓ | ✓ | ✗ | 1534/106 |
| eval_02_agent | agent | plan_write | ✓ | ✗ | ✗ | ✓ | 1526/263 |
| eval_03_agent | agent | plan_write | ✓ | ✓ | ✓ | ✗ | 1548/337 |
| eval_04_agent | agent | plan_write | ✓ | ✓ | ✓ | ✓ | 1525/542 |
| eval_05_agent | agent | plan_write | ✓ | ✓ | ✓ | ✗ | 1566/406 |
| eval_06_agent | agent | read_file | ✓ | ✓ | ✓ | ✗ | 1534/101 |
| eval_07_agent_question | agent_question | plan_write | ✓ | ✓ | ✓ | ✗ | 1520/528 |
| eval_08_plain | plain | — | ✓ | ✗ | ✗ | ✗ | 1474/858 |
| eval_09_agent | agent | plan_write | ✓ | ✓ | ✓ | ✗ | 1521/295 |
| eval_10_agent_question | agent_question | plan_write | ✓ | ✓ | ✓ | ✓ | 1548/443 |
| eval_11_agent | agent | plan_write | ✓ | ✓ | ✓ | ✓ | 1574/537 |
