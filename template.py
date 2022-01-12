import ast
import lark
import itertools

embed_parser = lark.Lark(r'''
%ignore " "
%import common.ESCAPED_STRING
%import common.CNAME

start : "{" embed "}" REST?

?embed : join
       | data

join : "join" data "with" string

?data : string

?string : string_atom
        | string_atom string

?string_atom : FIELD          -> field
             | ESCAPED_STRING -> esc_string
             | prod

prod : ESCAPED_STRING "*" COUNT

FIELD : ("." CNAME)+
COUNT : /\d+/
REST : /.+/s
''', parser='earley')

@lark.v_args(inline=True)
class Embed(lark.Transformer):
    def __init__(self, data):
        self.data = data
        self.requirements = set()


    def start(self, embed, rest=None):
        return embed[0]({})
    
    def join(self, data, string):
        requirements = data[1].union(string[1])
        iterator = create_iterator(self.data, requirements)

        join_pieces = []
        for indexes in iterator:
            join_pieces.append(str(data[0](indexes)))
        
        result = string[0]({}).join(join_pieces)
        return lambda indexes: result, set()
        
    def string(self, atom, rest):
        gen = lambda indexes: f'{atom[0](indexes)}{rest[0](indexes)}'
        requirements = atom[1].union(rest[1])
        return gen, requirements
    
    def field(self, key_path):
        gen = lambda indexes: get_field(key_path, self.data, indexes)
        requirements = {key_path}
        return gen, requirements
    
    def esc_string(self, value):
        result = ast.literal_eval(value)
        gen = lambda indexes: result
        requirements = set()
        return gen, requirements
    
    def prod(self, string, count):
        result = ast.literal_eval(string) * int(count)
        gen = lambda indexes: result
        requirements = set()
        return gen, requirements



def get_field(key, data, indexes):
    current_field = ''

    for field in key.split('.')[1:]:
        current_field += f'.{field}'
        data = data[field]
        if current_field in indexes:
            idx = indexes[current_field]
            data = data[idx]
        
    return data

def walk_fields(key, data, indexes):
    current_field = ''
    field_parts = key.split('.')[1:]
    result = []
    current_data = [data]

    for idx, field in enumerate(field_parts):
        current_field += f'.{field}'
        current_data = [x[field] for x in current_data]

        if current_field in indexes:
            idx = indexes[current_field]
            current_data = [x[idx] for x in current_data]

        if type(current_data[0]) == list:
            current_data = itertools.chain(*current_data)

    return current_data


def get_field_tree(fields):
  intermediates = set()
  for leaf_field in fields:
      path = leaf_field[1:].split('.')
      for idx in range(1, len(path)):
          interim = f'.{".".join(path[:idx])}'
          intermediates.add(interim)
  return fields.union(intermediates)

def get_lists(data, allowed_descent):
  remaining = [(f'.{k}', v) for k,v in data.items()]
  result = set()

  while remaining:
    current_key, current_val = remaining.pop()

    if current_key not in allowed_descent:
      continue

    if type(current_val) == list:
      result.add(current_key)
      for next_val in current_val:
        remaining.append((current_key, next_val))

    if type(current_val) == dict:
      for next_key, next_val in current_val.items():
        remaining.append((f'{current_key}.{next_key}', next_val))

  return result

  
def create_iterator(data, requirements):
    all_fields = get_field_tree(requirements)
    all_lists = sorted(get_lists(data, all_fields))

    print(all_lists)

    assert len(all_lists) == 1
    for idx in range(len(all_lists[0])):
      yield {all_lists[0]: idx}


def try_filling_template(template, data):
  try:
    start_token = embed_parser.parse(template)
    result = Embed(data).transform(start_token)
    if len(start_token.children) == 1:
      endpos = len(template) - 1
    else:
      endpos = start_token.children[1].start_pos
    
    while template[endpos] != '}':
      endpos -= 1
    
    return result, endpos + 1
      
  except lark.exceptions.UnexpectedCharacters as e:
    return None, 0


def fill_template(template, data):
  startpos = 0
  result = []
  while startpos < len(template) - 1:
    try:
      next_candidate = startpos + template[startpos:].index('{')
    except:
      result.append(template[startpos:])
      break

    if next_candidate != startpos:
      result.append(template[startpos:next_candidate])
      startpos = next_candidate

    fill_text, offset = try_filling_template(template[startpos:], data)
    if fill_text:
      result.append(fill_text)
      startpos += offset
    else:
      result.append(template[startpos])
      startpos += 1
    
  return ''.join(result)