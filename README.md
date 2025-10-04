
This programs awaits an alert signal from TradingView and automatically places a market order on TopstepX.

The trading strategy that is used here is the fractal model.

SET UP:


Make sure you have a Topstep account.
Go into TopstepX -> Settings -> API.
Link your account to ProjectX. Make sure to choose TopstepX. This will cost 14.99/month if you use the code 'topstep' during checkout.
After finishing up with ProjectX, come back to the API page on TopstepX and add an API key.
Go into a terminal/prompt on your computer and enter this command:

curl -X 'POST' \
  'https://api.topstepx.com/api/Auth/loginKey' \
  -H 'accept: text/plain' \
  -H 'Content-Type: application/json' \
  -d '{
    "userName": "USERNAME-HERE",
    "apiKey": "PUT-API-KEY-HERE"
  }'
  ngrok config add-authtoken 33XLwcGNDxmGoqLeTWehE0IF4Ga_7brvri2E2eZVtuZ6jMv2x
33XLwcGNDxmGoqLeTWehE0IF4Ga_7brvri2E2eZVtuZ6jMv2x
Make sure to put your username and API key in between the quotation marks.
This will give you something like this:

{"token":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJodHRwOi8vc2NoZW1hcy54bWxzb2FwLm9yZy93cy8yMDA1LzA1L2lkZW50aXR5L2NsYWltcy9uYW1laWRlbnRpZmllciI6IjE3NDQ2MSIsImh0dHA6Ly9zY2hlbWFzLnhtbHNvYXAub3JnL3dzLzIwMDUvMDUvaWRlbnRpdHkvY2xhaW1zL3NpZCI6ImIyYzdlNGFhLTc1ZGYtNDEzYS1hNzYyLWRjYTFhOWJjMWJAIJF9sidfj93dzLzIwMDUvMDUvaWRlbnRpdHkvY2xhaW1zL25hbWUiOiJkYXNodGluZSIsImh0dHA6Ly9zY2hlbWFzLm1pY3Jvc29mdC5jb20vd3MvMjAwOC8wNi9pZGVudGl0eS9jbGFpbXMvcm9sZSI6InVzZXIiLCJodHRwOi8vc2NoZW1hcy5taWNyb3NvZnQuY29tL3dzLzIwMDgvMDYvaWRlbnRpdHkvY2xhaW1zL2F1dGhlbnRpY2F0aW9ubWV0aG9kIjoiYXBpLWtleSIsIm1zZCI6WyJDTUVHUk9VUF9UT0IiLCJDTUVfVE9CIl0sIm1mYSI6InZlcmlmaWVkIiwiZXhwIjoxNzU5NTMzNTI4fQ.b3rc16PMlscFtPUOazVwlak4zVwvGogdCxz3_5m1rXA","success":true,"errorCode":0,"errorMessage":null}%

Copy the big string of random letters and numbers, everything between {"token": and ,"success":true,"errorCode":0,"errorMessage":null}%
Go into the topstepx_api.py file.
There is a variable called API_TOKEN. Set your token to this variable. Should look something like this:

API_TOKEN = "ThisISwhereYOUpasteYOURtoken"

Now, we need to get the id of the account we want.
To get list of accounts, run this cURL command:

curl -X POST "https://api.topstepx.com/api/Account/search" \
  -H "accept: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{"onlyActiveAccounts": true}'

Find the name of the account. Right before the name, there is an id. Copy that number and go back into app.py and set ACC_ID to it. Should look like this now:

ACC_ID = "9211230"

Lastly, we need the id of the contract we want to trade. Run this command:

curl -X POST "https://api.topstepx.com/api/Contract/available" \
  -H "accept: application/json" \
  -H "Authorization: Bearer YOUR_API_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{"live": false}'

Find the "id": of the contract. Might be easier to just copy that whole output, paste it into a notepad and ctrl+f.
Set it to CONTRACT_ID in app.py. Should look like this now: 

CONTRACT_ID = "CON.F.US.MNQ.Z25"
