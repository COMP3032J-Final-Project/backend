setlocal
FOR /F "tokens=*" %%i in ('type .env') do SET %%i
IF [%DB_PASSWORD%] == [] (mysql -u %DB_USERNAME% < db_initialize.txt) ELSE (mysql -u %DB_USERNAME% -p %DB_PASSWORD% < db_initialize.txt)
pip install -r requirements.txt