from flask import Flask
from flask import request
import os

app = Flask(__name__)

APP_TOKEN = os.environ['FB_ACCESS_TOKEN']
FB_MESSAGES_ENDPOINT = "https://graph.facebook.com/v2.6/me/messages"

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == "GET":
        if request.args.get('hub.verify_token') == 'todoist_is_my_fave':
            return request.args.get('hub.challenge')
        else:
            return 'Wrong validation token'
    else:
        if request.method == "POST":
            data = request.json()
            sender_id = data["entry"][0]["messaging"][0]["sender"]["id"]
			send_back_to_fb = {
		        "recipient": {
		            "id": sender_id,
		        },
		        "message": "this is a test response message"
		    }
            fb_response = requests.post(FB_MESSAGES_ENDPOINT,
                                params={"access_token": FB_TOKEN},
                                data=send_back_to_fb)
            if not fb_response.ok:
            	print 'jeepers. %s: %s' % (fb_response.status_code, fb_response.text)
        return "OK", 200

if __name__ == "__main__":
	app.run(host="0.0.0.0", port=5000)