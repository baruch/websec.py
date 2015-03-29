from webseclib.websec import WebSec

def run_utility()
	app = WebSec()
	app.load_config()
	app.load_state()
	app.run()
	app.save_state()
