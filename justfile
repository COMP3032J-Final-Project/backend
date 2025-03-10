dev:
  fastapi dev ./app

prod:
  fastapi run --workers 4 ./app
