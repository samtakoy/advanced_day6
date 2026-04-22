# ft_client — пакет для fine-tuning бэкендов.
# Каждый бэкенд живёт в своей подпапке:
#   src.ft_client.openai — OpenAI API (upload → create_job → poll)
#   src.ft_client.mlx    — локальный MLX QLoRA (train → export в Ollama)
