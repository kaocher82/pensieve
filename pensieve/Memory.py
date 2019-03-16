from slytherin.collections import remove_list_duplicates
from slytherin import get_size
from memoria import make_hash_sha256
import dill

from datetime import datetime

def get_elapsed_seconds(start, end):
	delta = end - start
	return delta.seconds + delta.microseconds / 1E6

class Memory:
	def __init__(self, key, function, pensieve, precursors=None, safe=True, meta_data=False, _update=True, _stale=True):
		"""
		:type key: str
		:type precursors: list[Memory] or NoneType
		:type pensieve: Pensieve
		:type function: function
		:type safe: bool
		:param safe: when True only a copy of the content is returned to avoid mutating it from outside
		"""
		# make precursors unique
		precursors = precursors or []
		self._key = key
		self._pensieve = pensieve
		self._content = None
		self._hash = None
		self._safe = safe
		if self.key not in self.pensieve._successor_keys:
			self.pensieve._successor_keys[self.key] = []
		if self.key not in self.pensieve._precursor_keys:
			self.pensieve._precursor_keys[self.key] = []
		self._frozen = False
		self._stale = _stale
		self._function = None
		self._meta_data = meta_data or {}
		self._last_evaluated = None
		self._elapsed_seconds = None
		self._size = None

		if _update:
			self.update(precursors, function)

	@property
	def size(self):
		if self._size is None:
			result = 0
			result += get_size(self._key, exclude_objects=[self._pensieve])
			result += get_size(self._content, exclude_objects=[self._pensieve])
			result += get_size(self._hash, exclude_objects=[self._pensieve])
			result += get_size(self._safe, exclude_objects=[self._pensieve])
			result += get_size(self._frozen, exclude_objects=[self._pensieve])
			result += get_size(self._stale, exclude_objects=[self._pensieve])
			result += get_size(self._function, exclude_objects=[self._pensieve])
			result += get_size(self._meta_data, exclude_objects=[self._pensieve])
			result += get_size(self._last_evaluated, exclude_objects=[self._pensieve])
			result += get_size(self._elapsed_seconds, exclude_objects=[self._pensieve])
			result += get_size(result)
			self._size = result
		return self._size

	@property
	def speed(self):
		if self._elapsed_seconds:
			return self.size/self._elapsed_seconds
		else:
			return None

	def __sizeof__(self):
		return self.size

	def __eq__(self, other):
		return isinstance(other, Memory) and self.key == other.key

	def __hash__(self):
		return hash(self.key)

	def __repr__(self):
		return f'Memory:{self.key}'

	def __getstate__(self):
		"""
		:rtype: dict
		"""
		stale = self._stale
		if stale:
			# if memory is stale there is no point in storing its content
			content = None
		else:
			try:
				content = dill.dumps(obj=self._content)
			except:
				# if we fail to serialize the content of the memory we store it as stale
				# so the next time it is remembered, i.e., loaded, it will be reconstructed
				content = None
				stale = True


		state = {
			'key': self._key,
			'content': content,
			'hash': self._hash,
			'safe': self._safe,
			'frozen': self._frozen,
			'stale': stale,
			'meta_data': self._meta_data,
			'function': dill.dumps(obj=self._function),
			'last_evaluated': self._last_evaluated,
			'elapsed_seconds': self._elapsed_seconds
		}
		return state

	def __setstate__(self, state):
		"""
		:type state: dict
		"""
		self._key = state['key']
		self._content = dill.loads(str=state['content'])
		self._hash = state['hash']
		self._safe = state['safe']
		self._frozen = state['frozen']
		self._stale = state['stale']
		self._meta_data = state['meta_data']
		self._function = dill.loads(str=state['function'])
		self._pensieve = None
		self._last_evaluated = state['last_evaluated']
		self._elapsed_seconds = state['elapsed_seconds']

	@classmethod
	def from_state(cls, state, pensieve):
		memory = Memory(
			key=state['key'],
			function=dill.loads(str=state['function']),
			pensieve=pensieve,
			precursors=None,
			safe=state['safe'],
			meta_data=state['meta_data'],
			_update=False, _stale=state['stale']
		)
		memory._content = dill.loads(str=state['content'])
		memory._frozen = state['frozen']
		memory._stale = state['stale']
		memory._last_evaluated = state['last_evaluated']
		memory._elapsed_seconds = state['elapsed_seconds']
		return memory


	@property
	def is_frozen(self):
		return self._frozen

	@property
	def is_stale(self):
		return self._stale

	def freeze(self):
		self._frozen = True

	def unfreeze(self):
		self._frozen = False
		if self._stale:
			self.mark_stale()

	@property
	def pensieve(self):
		"""
		:rtype: .Pensieve.Pensieve
		"""
		return self._pensieve


	@property
	def key(self):
		return self._key

	@property
	def label(self):
		key = self.key.replace('__', '\n').replace('_', ' ')
		if self.is_stale and self.is_frozen:
			return f'{key}\n(stale & frozen)'
		elif self.is_stale and not self.is_frozen:
			return f'{key}\n(stale)'
		elif not self.is_stale and self.is_frozen:
			return f'{key}\n(frozen)'
		else:
			return f'{key}'

	@property
	def precursor_keys(self):
		"""
		:type: list[str]
		"""
		return list(self.pensieve.get_precursor_keys(memory=self))

	@property
	def successors(self):
		return self.pensieve.get_successors(memory=self)

	@property
	def has_precursors(self):
		return len(self.precursor_keys) > 0

	@property
	def successor_keys(self):
		"""
		:type: list[str]
		"""
		return list(self.pensieve.get_successor_keys(memory=self))

	@property
	def precursors(self):
		return self.pensieve.get_precursors(memory=self)

	@property
	def has_successors(self):
		return len(self.successor_keys) > 0

	def erase_successor(self, successor):
		"""
		:param Memory or str successor: the successor memory or its key that should be removed
		"""
		if isinstance(successor, str):
			self.pensieve._successor_keys[self.key].remove(successor)
		else:
			self.pensieve._successor_keys[self.key].remove(successor.key)

	# ************************* COMPUTATION **********************************

	def update(self, precursors, function, meta_data=None):
		"""
		:type precursors: list[Memory]
		:type function: callable
		"""
		# make precursors unique:
		precursors = precursors or []
		precursors = remove_list_duplicates(precursors)

		precursor_keys = [p.key for p in precursors]

		removed_precursor_keys = [key for key in self.precursor_keys if key not in precursor_keys]
		new_precursor_keys = [key for key in precursor_keys if key not in self.precursor_keys]

		self.pensieve._precursor_keys[self.key] = precursor_keys
		for precursor_key in removed_precursor_keys:
			self.pensieve._successor_keys[precursor_key].remove(self.key)
		for precursor_key in new_precursor_keys:
			self.pensieve._successor_keys[precursor_key].append(self.key)

		self._function = function
		self.mark_stale()

		if meta_data is not None:
			self._meta_data = meta_data

	@property
	def content(self):
		return self._content

	@content.setter
	def content(self, content):
		if self.is_frozen:
			raise RuntimeError('Memory: You cannot change a frozen memory!')

		# only mark successors stale if the content changes
		if make_hash_sha256(content) != make_hash_sha256(self._content):
			for successor in self.successors:
				successor.mark_stale()

		self._content = content

	def mark_stale(self):
		self._stale = True
		self._size = None

	def evaluate(self):
		if not self.is_stale or self.is_frozen:
			return self.content
		precursor_keys_to_contents = {p.key: p.evaluate() for p in self.precursors}
		self._stale = False

		start_time = datetime.now()

		if len(self.precursor_keys) == 0:
			self.content = self._function()
		elif len(self.precursor_keys) == 1:
			precursor_key = list(precursor_keys_to_contents.values())[0]
			self.content = self._function(precursor_key)
		else:
			inputs = PensieveEvaluationInput(precursor_keys_to_contents)
			self.content = self._function(inputs)

		self._hash = make_hash_sha256(self.content)

		end_time = datetime.now()
		self._elapsed_seconds = get_elapsed_seconds(start=start_time, end=end_time)
		self._last_evaluated = end_time

		return self.content

	@property
	def graphviz_edges_str(self):
		if not self.has_precursors:
			return self.label if not self.has_successors else None
		else:
			edges = [
				f'{precursor.label} -> {self.label}'
				for precursor in self.precursors
			]
			return '\n'.join(edges)

	def __graph_dict__(self):
		"""
		:rtype: dict
		"""
		return {
			'label': self.label,
			'value': None,
			'meta_data': self._meta_data
		}


class PensieveEvaluationInput():
	def __init__(self, inputs):
		self.__dict__ = inputs

	def __getitem__(self, name):
		return self.__dict__[name]

# end of file