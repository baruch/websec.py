from webseclib.page import Page

ign_sec_start = re.compile(r'^\s*\[\s*(.+)\s*\]\s*$')

class Config:
	def __init__(self):
		self.pages = []
		self.def_page = Page()

	def determine_conf_files(self, ignore_file, urllist_file):
		if not urllist_file:
			# No url list file, use a default
			urllist_file = '~/.websec/url.list'
			if ignore_file is None:
				# An ignore file wasn't specified either, use a default
				ignore_file = '~/.websec/ignore.list'
		return (ignore_file, urllist_file)

	def load(self, ignore_file=None, urllist_file=None):
		(ignore_file, urllist_file) = self.determine_conf_files(ignore_file, urllist_file)
		self.ignores = self.load_ignore(ignore_file)
		self.pages = self.load_pages(urllist_file)
	
	def load_ignore(self, ignore_file):
		ignores = {}
		if ignore_file is None:
			return ignores

		infile = file(ignore_file, 'r')
		ignore = Ignore()
		name = None
		for line in infile:
			# Ignore comments in the line
			(line, comment) = (line+'#').split('#', 1)
			
			# Match section starts
			match = ign_sec_start.match(line)
			if match
