from flask import Flask, jsonify, request

app = Flask(__name__)

# Sample endpoint
@app.route('/api/v1/message', methods=['POST'])
def send_message():
    data = request.json
    # Here you can add logic to handle the incoming message
    return jsonify({'status': 'success', 'message': data}), 200

# Error handling example
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

if __name__ == '__main__':
    app.run(debug=True)