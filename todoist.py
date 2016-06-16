from flask import Flask

app = Flask(__name__)

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == "GET":
        if request.args.get('hub.verify_token') == 'todoist_is_my_fave':
            return Response(request.args.get('hub.challenge'))
        else:
            return Response('Wrong validation token')

if __name__ == "__main__":
	app.run(host="0.0.0.0", port=5000)