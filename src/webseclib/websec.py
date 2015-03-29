from webseclib.config import Config
from webseclib.state import State

class WebSec:
	def __init__(self):
		self.config = Config()
		self.state = State()

	def load_config(self, ignore_file=None, urllist_file=None):
		self.config.load(ignore_file, urllist_file)

	def load_state(self):
		self.state.load(self.config.state_file)

	def save_state(self):
		self.state.save(self.config.state_file)

	def run(self):
		for page in self.config.pages:
			tmp_filename = self.fetch_single(page.url)
			page.run(tmp_filename)
		pass
	
	def fetch_single(self, url):
		url_state = self.state.get_state(url)
		out_filename = '/tmp/websec.tmp'
		http_fetch(url, url_state, out_filename)
		pass
