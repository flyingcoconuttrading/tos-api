import schwab

client = schwab.auth.client_from_login_flow(
    api_key="YOUR_APP_KEY",
    app_secret="YOUR_APP_SECRET",
    callback_url="https://127.0.0.1",
    token_path="token.json"
)

print("Success! token.json saved.")
