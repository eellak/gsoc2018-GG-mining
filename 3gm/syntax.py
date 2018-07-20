from entities import *
import re
import collections
import logging
import helpers
import tokenizer
import itertools
import copy

try:
	import spacy
	from spacy import displacy
	import el_unnamed
	nlp = el_unnamed.load()
except ImportError:
	pass


class UncategorizedActionException(Exception):
	"""This exception is raised whenever an action cannot be
	classified.
	"""

	def __init__(self, s):
		self.message = 'Uncategorized Action: {}'.format(s)
		super().__init__(self.message)

	def __str__(self): return self.message

	def __repr__(self): return self.message


# Action Tree Generation

class ActionTreeGenerator:
	"""
		Generate the action tree for a given extract.
		The action tree consists of:
		1. action to do (i.e. add, remove, ammend) as the root of the tree
		2. on what to act (i.e. add a paragraph)
		3. where to do it (i.e. on which law after which section)
	"""

	def __call__(self, s):
		return ActionTreeGenerator.generate_action_tree_from_string(s)

	trans_lookup = {
		'άρθρ': 'article',
		'παράγραφ': 'paragraph',
		'εδάφ': 'period',
		'φράσ': 'phrase',
		'περίπτωσ' : 'case',
		'υποπερίπτωσ' : 'subcase'
	}

	children_loopkup = {
		'law' : ['article'],
		'article' : ['paragraph'],
		'paragraph' : ['period', 'case'],
		'period' : ['phrase'],
		'case' : ['subcase'],
		'subcase' : [],
		'phrase' : []
	}

	@staticmethod
	def get_latest_statute(statutes):
		"""Returns latest statute in a given list of
		statutes by first splitting the statutes and then
		finding the one with the latest year
		"""
		statutes_ = [re.split(r'[/ .]', statute)[-1] for statute in statutes]
		latest = None
		latest_statute = None
		for i, s in enumerate(statutes_):
			if s.isdigit():
				if not latest or latest <= int(s):
					latest = int(s)
					latest_statute = statutes[i]
		if not latest:
			return statutes[0]

		return latest_statute

	@staticmethod
	def detect_latest_statute(extract):
		legislative_acts = list(re.finditer(legislative_act_regex, extract))
		laws = list(re.finditer(law_regex, extract))
		presidential_decrees = list(re.finditer(
			presidential_decree_regex, extract))
		legislative_decrees = list(
			re.finditer(
				legislative_decree_regex,
				extract))

		laws.extend(presidential_decrees)
		laws.extend(legislative_acts)
		laws.extend(legislative_decrees)

		laws = [law.group() for law in laws]

		logging.info('Laws are', laws)

		law = ActionTreeGenerator.get_latest_statute(laws)

		return law

	@staticmethod
	def generate_action_tree_from_string(
			s,
			nested=False,
			max_what_window=20,
			max_where_window=30,
			use_regex=False):
		global actions
		global whats

		trees = []

		# get extracts and non-extracts using helper functions
		extracts, non_extracts = helpers.get_extracts(s)

		logging.info(extracts)

		logging.info(non_extracts)

		logging.info('Joining non_extracts')

		non_extracts = ' '.join(non_extracts)

		logging.info(non_extracts)

		logging.info('Splitting with tokenizer')

		non_extracts = tokenizer.tokenizer.split(non_extracts, remove_subordinate=True, delimiter='. ')

		logging.info(non_extracts)

		extract_cnt = 0

		for non_extract in non_extracts:

			doc = nlp(non_extract)

			tmp = list(map(lambda s: s.strip(
				string.punctuation), non_extract.split(' ')))

			for action in actions:
				for i, w in enumerate(doc):
					if action == w.text:
						tree = collections.defaultdict(dict)
						tree['root'] = {
							'_id': i,
							'action': action.__str__(),
							'children': []
						}
						max_depth = 0

						logging.info('Found ' + str(action))

						extract = None
						if str(action) not in ['διαγράφεται', 'παύεται', 'καταργείται']:
							try:
								extract = extracts[extract_cnt]
								extract_cnt += 1
							except IndexError:
								extract = None

						found_what, tree, is_plural = ActionTreeGenerator.get_nsubj(
							doc, i, tree)
						if found_what:
							k = tree['what']['index']
							if tree['what']['context'] not in [
									'φράση', 'φράσεις']:
								tree['what']['number'] = list(
									helpers.ssconj_doc_iterator(doc, k, is_plural))

							logging.info(tree['what'])

						else:
							found_what, tree, is_plural = ActionTreeGenerator.get_nsubj_fallback(
								tmp, tree, i)

						# get content
						tree, max_depth = ActionTreeGenerator.get_content(
							tree, extract, s)

						# split to subtrees
						subtrees = ActionTreeGenerator.split_tree(tree)

						# iterate over subtrees
						for subtree in subtrees:

							subtree, max_depth = ActionTreeGenerator.get_content(
								subtree, extract, s, secondary=True)

							# get latest statute
							law = ActionTreeGenerator.detect_latest_statute(
								non_extract)

							# first level are laws
							subtree['law'] = {
								'_id': law,
								'children': ['article']
							}

							splitted = non_extract.split(' ')

							# build levels bottom up
							subtree = ActionTreeGenerator.build_levels(splitted, subtree)

							# nest into dictionary
							if nested:

								ActionTreeGenerator.nest_tree('root', subtree)

							trees.append(subtree)


		return trees

	@staticmethod
	def nest_tree_helper(vertex, tree):
		if tree[vertex] == {}:
			return tree
		if tree[vertex]['children'] == []:
			del tree[vertex]['children']
			return tree
		if len(tree[vertex]['children']) == 1:
			try:
				c = tree[vertex]['children'][0]
				del tree[vertex]['children']
				tree[vertex][c] = tree[c]
				ActionTreeGenerator.nest_tree(c, tree)
			except:
				return tree

	@staticmethod
	def nest_tree(vertex, tree):
		ActionTreeGenerator.nest_tree_helper(vertex, tree)

	@staticmethod
	def get_nsubj(doc, i, tree):
		global whats
		found_what = False
		root_token = doc[i]
		for child in root_token.children:

			if child.dep_ in ['nsubj', 'obl']:
				for what in whats:
					if child.text == what:
						found_what = True
						tree['root']['children'].append('law')
						tree['what'] = {
							'index': child.i,
							'context': what,
						}
						logging.info('nlp ok')

						is_plural = helpers.is_plural(what)

						return found_what, tree, is_plural

		return found_what, tree, False

	@staticmethod
	def get_nsubj_fallback(tmp, tree, i, max_what_window=20):
		found_what = False
		logging.info('Fallback mode')
		logging.info(tmp)
		for j in range(1, max_what_window + 1):
			for what in whats:
				if i + j <= len(tmp) - 1 and what == tmp[i + j]:
					tree['root']['children'].append('law')
					tree['what'] = {
						'index': i + j,
						'context': what,
					}

					if i + j + 1 <= len(tmp):
						tree['what']['number'] = list(helpers.ssconj_doc_iterator(tmp, i + j))
					else:
						tree['what']['number'] = None


					is_plural = helpers.is_plural(what)
					return found_what, tree, is_plural

				if i - j >= 0 and what == tmp[i - j]:
					tree['root']['children'].append('law')
					tree['what'] = {
						'index': i - j,
						'context': what,
					}
					if i - j >= 0:
						tree['what']['number'] = list(helpers.ssconj_doc_iterator(tmp, i - j))
					else:
						tree['what']['number'] = None

					is_plural = helpers.is_plural(what)
					return found_what, tree, is_plural


		return found_what, tree, False

	@staticmethod
	def get_rois_from_extract(q, what, idx_list):
		queries = []
		for idx in idx_list:
			if what in ['παράγραφος', 'παράγραφοι']:
				x = idx + '. '
			elif what in ['άρθρο', 'άρθρα']:
				x = 'Άρθρο ' + idx
			elif what in ['περίπτωση', 'περιπτώσεις', 'υποπερίπτωση', 'υποπεριπτώσεις']:
				x = idx + '. '
			queries.append(x)

		spans = []
		for x in queries:
			match = re.search(x, q)
			if match:
				spans.append(match.span()[0])
		spans.append(len(q))
		spans.sort()

		result = []
		for i in range(len(spans) - 1):
			start = spans[i]
			end = spans[i + 1]
			result.append(q[start:end])

		return result

	@staticmethod
	def split_tree(tree):

		try:
			idx_list = tree['what']['number']
			extract = tree['what']['content']
			what = tree['what']['context']
		except BaseException:
			tree['what']['number'] = tree['what']['number'][0]
			return [tree]

		if len(idx_list) == 1:
			tree['what']['number'] = idx_list[0]
			result = [tree]

		else:
			result = []
			contents = ActionTreeGenerator.get_rois_from_extract(
				extract, what, idx_list)
			for idx, s in itertools.zip_longest(idx_list, contents):
				tmp = copy.deepcopy(tree)
				tmp['what']['number'] = idx
				tmp['what']['content'] = s
				result.append(tmp)

		return result

	@staticmethod
	def get_content(tree, extract, s, secondary=False):
		max_depth = 0

		if tree['what']['context'] in ['άρθρο', 'άρθρα']:
			if tree['root']['action'] != 'διαγράφεται':
				content = extract if not secondary else tree['what']['content']
				tree['article']['content'] = content
				tree['what']['content'] = content
			max_depth = 3

		elif tree['what']['context'] in ['παράγραφος', 'παράγραφοι']:
			if tree['root']['action'] != 'διαγράφεται':
				content = extract if not secondary else tree['what']['content']
				tree['paragraph']['content'] = content
				tree['what']['content'] = content
			max_depth = 4

		elif tree['what']['context'] in ['εδάφιο', 'εδάφια']:
			if tree['root']['action'] != 'διαγράφεται':
				content = extract if not secondary else tree['what']['content']
				tree['what']['content'] = content
			max_depth = 5

		elif tree['what']['context'] in ['περίπτωση', 'περιπτώσεις']:
			if tree['root']['action'] != 'διαγράφεται':
				content = extract
				tree['what']['content'] = content
			max_depth = 5

		elif tree['what']['context'] in ['υποπερίπτωση', 'υποπεριπτώσεις']:
			if tree['root']['action'] != 'διαγράφεται':
				content = extract
				tree['what']['content'] = content
			max_depth = 5



		elif tree['what']['context'] in ['φράση', 'φράσεις']:
			location = 'end'
			max_depth = 6

			# get old phrase
			before_phrase = re.search(' μετά τη φράση «', s)
			after_phrase = re.search(' πριν τη φράση «', s)
			old_phrase = None
			if before_phrase or after_phrase:
				if before_phrase:
					start_of_phrase = before_phrase.span()[1]
					end_of_phrase = re.search('»', s[start_of_phrase:]).span()[
						0] + start_of_phrase
					location = 'before'
					old_phrase = s[start_of_phrase: end_of_phrase]
				elif after_phrase:
					start_of_phrase = after_phrase.span()[1]
					end_of_phrase = re.search(
						'»', s[start_of_phrase:]).span()[0]
					location = 'after'
					old_phrase = s[start_of_phrase: end_of_phrase]

			new_phrase = None
			phrase_index = re.search(' η φράση(|,) «', s)

			if phrase_index:
				start_of_phrase = phrase_index.span()[1]
				end_of_phrase = re.search('»', s[start_of_phrase:]).span()[
					0] + start_of_phrase
				new_phrase = s[start_of_phrase + 2: end_of_phrase - 2]

			if old_phrase and new_phrase:
				tree['what']['location'] = location
				tree['what']['old_phrase'] = old_phrase
				tree['what']['new_phrase'] = new_phrase
				tree['what']['content'] = new_phrase


		return tree, max_depth

	@staticmethod
	def detect_from_regex(non_extract, regex):
		roi = list(
			filter(
				lambda x: x != [], [
					list(
						re.finditer(
							a, non_extract)) for a in regex]))
		return int(paragraph[0][0].group().split(' ')[1])

	@staticmethod
	def detect_with_iterator(non_extract_split, words):
		for i, w in enumerate(non_extract_split):
			if w in words:
				try:
					iters = list(
						helpers.ssconj_doc_iterator(
							non_extract_split, i))
					return iters[0]
				except BaseException:
					continue


	@staticmethod
	def build_level(tmp, subtree, max_depth, stem):
		lookup = ActionTreeGenerator.trans_lookup[stem]

		if not re.search(stem, subtree['what']['context']):
			for i, w in enumerate(tmp):
				if re.search(stem, w):
					subtree[lookup]['_id'] = next(helpers.ssconj_doc_iterator(tmp, i))
					subtree[lookup]['children'] = ActionTreeGenerator.children_loopkup[lookup]
					break
		else:
			subtree[lookup]['_id'] = subtree['what']['number']
			subtree[lookup]['children'] = []


		return subtree

	@staticmethod
	def build_levels(tmp, subtree):
		stems = list(ActionTreeGenerator.trans_lookup.keys())
		for i, stem in enumerate(stems):
			subtree = ActionTreeGenerator.build_level(tmp, subtree, i + 2, stem)

		return subtree

	@staticmethod
	def phrase_analyze(s):
		s = tokenizer.tokenizer.remove_subordinate(s)
		parts = s.split(' ')
		phrase_regex = r'φράση «[^»]*»'

		tree = collections.defaultdict(dict)
		for i, p in enumerate(parts):
			for action in actions:
				if action == p:
					break

		for i, p in enumerate(parts):
			for what_stem in what_stems:
				if re.search(what_stem, p):
					is_plural = helpers.is_plural(p)
					it = helpers.ssconj_doc_iterator(parts, i, is_plural=is_plural)
					lookup = ActionTreeGenerator.trans_lookup[what_stem]
					tree[lookup]['_id'] = next(it)



		for x in re.finditer(phrase_regex, s):
			print(helpers.get_extracts(x.group(), min_words=0))

		law = ActionTreeGenerator.detect_latest_statute(s)
