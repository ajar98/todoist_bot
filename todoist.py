from flask import Flask
from flask import request

app = Flask(__name__)

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == "GET":
        if request.args.get('hub.verify_token') == 'todoist_is_my_fave':
            return request.args.get('hub.challenge')
        else:
            return 'Wrong validation token'

if __name__ == "__main__":
	app.run(host="0.0.0.0", port=5000)