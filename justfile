dev:
  fastapi dev ./app

prod:
  fastapi run --workers 4 ./app

sync-dp-lock:
  uv pip sync ./requirements.txt
  uv pip install -r ./requirements.txt
  uv pip freeze > requirements_full.txt
