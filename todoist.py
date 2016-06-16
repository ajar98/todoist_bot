from flask import Flask
from flask import request
from webob import Response

app = Flask(__name__)

APP_TOKEN = "EAAPGnoxDIZC8BAMZBw6SgZCKZAga4nYg0XWHK1QwbJkEvdxzQs6hNV2QoZBxDg1hYJWf9S0LCxwloKjjKutzNFsXfkX5UxO5mNK4TeGMXNYQZA1IW3Sg8OCykvAt4ZBB7nUtJlIZBeHXcjdf4QACUm71bSZBVosUyITnJr0Nu7grAFwZDZD"

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == "GET":
        if request.args.get('hub.verify_token') == 'todoist_is_my_fave':
            return request.args.get('hub.challenge')
        else:
            return 'Wrong validation token'
    else:
        if request.method == "POST":
            event = request.get_json()
            resp = Response(status=200, mimetype='application/json')
            respond_FB("1062809190474751", "Hi! to you!")
            return resp

def respond_FB(sender_id, text):
    json_data = {
        "recipient": {"id": sender_id},
        "message": {"text": text}
    }
    params = {
        "access_token": APP_TOKEN
    }
    r = requests.post('https://graph.facebook.com/v2.6/me/messages', json=json_data, params=params)
    print(r, r.status_code, r.text)

if __name__ == "__main__":
	app.run(host="0.0.0.0", port=5000)