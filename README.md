# [SchemaLink](https://schemalink.biodata.di.unimi.it/)

<img src="https://github.com/AnacletoLAB/schemalink-webapp/blob/main/apps/arrows-ts/public/arrows_logo.svg" alt="SchemaLink logo" width="300" />

Web-based tool for drawing schemas.


## Run locally

1. Git clone/Download and unzip [​schemalink-webapp](https://github.com/AnacletoLAB/schemalink-webapp)​ and [​schemalink-api](https://github.com/AnacletoLAB/schemalink-api)​.

2. Install and start postgres on port 5432. For instance, on MacOS:
    - brew install postgresql
    - brew services start postgresql
    - dropdb Authentication
    - createdb Authentication
    - psql -d Authentication -f schemalink-api/authentication_database.sql
    - createuser -s postgres 
    - psql -d postgres
    - ALTER USER postgres WITH password 'unimi'; 
    - \q
    
    Note: Ensure postgres runs on port 5432 (check that the port is free).

3. Install and start ChromaDB. For instance, on MacOS:
    - brew install sqlite3
    - pip install -r schemalink-api/requirements.txt
    - sqlite3 schemalink-api/chroma_data/chroma.sqlite3 < schemalink-api/vector_store.sql
    - chroma run --port 8001 --path schemalink-api/chroma_data
    
    Note: Ensure postgres runs on port 8001 (check that the port is free).
    
4. Open a new shell tab, and start the API:
    - cd schemalink-api
    - cp .env.template .env
    - Open `.env` and fill in your values:
        - `OPENAI_API_KEY` — required for intelligent operations
        - `ADMIN_EMAIL` and `EMAIL_PASSWORD` — required for gmail-based functionalities (app password can be generated at: https://myaccount.google.com/apppasswords)
        - `SCHEMALINK_ENGINE_URL` — required for extraction (URL of your SchemaLink engine instance)
    - fastapi dev main.py
    
    Note: Ensure the API runs on port 8000 (check that the port is free).
    
5. Open a new shell tab, and start the webapp:
    - cd schemalink-webapp
    - npm install
    - npm audit fix
    - npx nx serve arrows-ts
    
    Note: Ensure the webapp runs on port 4200 (check that the port is free). 
    
6. Log-in webapp (browser --> localhost:4200) with admin credentials (can be edited): usr="schemalink"; pwd="Admin123!". Edit admin e-mail to exploit gmail-based functionalities. 


## Issues and Feedback

To report a problem that needs fixing, please create an
[issue](https://github.com/AnacletoLAB/schemalink-webapp/issues).

For suggestions and feedback, please start a
[discussion](https://github.com/AnacletoLAB/schemalink-webapp/discussions).
