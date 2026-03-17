cat > schwab_auth.py << 'EOF'
import schwab

client = schwab.auth.client_from_login_flow(
    api_key="RCB4dFxgAcpxlTwnRfApHGqkjHrbbkXobMEUvR3YEPHmL8pq",
    app_secret="oWoE6Vc5vU3NVnungD59IdprhHrV8hhkiUfAGCO197GVzGpTpvru6OeGeIdAKMZp",
    callback_url="https://127.0.0.1",
    token_path="token.json"
)

print("Success! token.json saved.")
EOF