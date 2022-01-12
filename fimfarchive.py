import ast
import json
from lark import v_args
from query import QueryFilter
from bs4 import BeautifulSoup
import ebooklib
import ebooklib.epub
import re
import os
import requests
import glob

class Fimfarchive:
    def __init__(self, unpacked_path):
        self.unpacked_path = unpacked_path

        with open(f"{unpacked_path}/index.json", encoding='utf8') as index_file:
            index = json.load(index_file)

        self.tags_by_type = {}
        self.tags_by_id = {}
        self.tags_by_name = {}
        self.stories_by_tag = {}
        self.stories_by_id = {}
        self.delta_index = {}

        for story_id, story_data in index.items():
            self.stories_by_id[story_id] = story_data
            for tag_data in story_data['tags']:
                tag_id = tag_data['id']
                tag_name = tag_data['name'].lower()
                tag_type = tag_data['type'].lower()

                tag_bucket = self.tags_by_type.setdefault(tag_type, {})
                tag_bucket[tag_id] = tag_name

                story_bucket = self.stories_by_tag.setdefault(tag_id, set())
                story_bucket.add(story_id)

                reverse_bucket = self.tags_by_name.setdefault(tag_name, set())
                reverse_bucket.add(tag_id)

                self.tags_by_id[tag_id] = tag_data
        
        self.tag_filter = TagFilter(self)
        self.story_filter = StoryFilter(self)
    
    def query_tags(self, query):
        return self.tag_filter.parse(query)
    
    def query_stories(self, query):
        return self.story_filter.parse(query)
    
    def get_cached_chapters(self, story_id):
        result = []
        for chapter_index in range(len(self.stories_by_id[story_id]['chapters'])):
            cache_path = os.path.join(self.unpacked_path, 'txt', story_id, f'{chapter_index}.txt')
            with open(cache_path) as input:
                result.append(input.read())
        return result
    
    def cache_chapters(self, story_id):
        epub_relpath = self.stories_by_id[story_id]['archive']['path']
        epub_path = os.path.join(self.unpacked_path, epub_relpath)
        retrieved_chapters = get_epub_chapters(epub_path, self.stories_by_id[story_id]['chapters'])

        txt_cache_path = os.path.join(self.unpacked_path, 'txt', story_id)
        os.makedirs(txt_cache_path, exist_ok=True)

        if not retrieved_chapters:
            epub_path = fetch_epub(self.unpacked_path, story_id)
            retrieved_chapters = get_epub_chapters(epub_path, self.stories_by_id[story_id]['chapters'])
        
        if retrieved_chapters:
            if len(retrieved_chapters) == len(self.stories_by_id[story_id]['chapters']):
                cache_epub_chapters(retrieved_chapters, txt_cache_path)
                return

        chapters = self.stories_by_id[story_id]['chapters']
        html_path = fetch_chapters(self.unpacked_path, story_id, chapters)
        retrieved_chapters = get_html_chapters(html_path)

        if retrieved_chapters:
            if len(retrieved_chapters) == len(self.stories_by_id[story_id]['chapters']):
                cache_html_chapters(retrieved_chapters, txt_cache_path, self.stories_by_id[story_id])
                return
        
        if not retrieved_chapters:
            print('cannot get chapters for story:', self.stories_by_id[story_id]['url'])

        if len(retrieved_chapters) != len(self.stories_by_id[story_id]['chapters']):
            print('invalid chapter count:', self.stories_by_id[story_id]['url'])
            print(' -- goes in', epub_path)


def fetch_epub(unpacked_path, story_id):
    os.makedirs(os.path.join(unpacked_path, 'epub-delta'), exist_ok=True)
    cache_path = os.path.join(unpacked_path, 'epub-delta', f'{story_id}.epub')
    if os.path.exists(cache_path):
        return cache_path
    
    epub_url = f'https://www.fimfiction.net/story/download/{story_id}/epub'

    try:
        print('fetching epub', epub_url)
        page = requests.get(epub_url, stream=True)
        epub_data = page.raw.read()
        with open(cache_path, 'wb') as output:
            output.write(epub_data)
    except:
        print('failed to fetch', epub_url)
    
    return cache_path

def fetch_chapters(unpacked_path, story_id, chapters):
    cache_dir = os.path.join(unpacked_path, 'html', f'{story_id}')
    os.makedirs(cache_dir, exist_ok=True)
    
    for chapter in chapters:
        chapter_path = os.path.join(cache_dir, f"{chapter['chapter_number']}.html")
        if os.path.exists(chapter_path):
            continue

        id = chapter['id']
        html_url = f'https://www.fimfiction.net/chapters/download/{id}/html'
        print('fetching chapter', html_url)
        stream = requests.get(html_url, stream=True)
        if stream.status_code < 200 or stream.status_code >= 400:
            print('failed to fetch', html_url)
            continue

        html_data = stream.content
        with open(chapter_path, 'wb') as f:
            f.write(html_data)
    
    return cache_dir

def get_html_chapters(html_cache_dir):
    chapter_paths = glob.glob(f'{html_cache_dir}/*')
    chapter_html = {}

    for chapter_path in chapter_paths:
        chapter_id = int(os.path.splitext(os.path.basename(chapter_path))[0])
        chapter_html[chapter_id] = chapter_path
    
    result = []
    for i in sorted(chapter_html.keys()):
        result.append(chapter_html[i])
    return result
        

def cache_html_chapters(chapter_paths, story_cache_path, story_index_data):
    for i, chapter_path in enumerate(chapter_paths):
        chapter_index = i + 1
        chapter_cache_path = os.path.join(story_cache_path, f'{chapter_index}.txt')
        if os.path.exists(chapter_cache_path):
            continue
        
        with open(chapter_path, encoding='utf8') as f:
            chapter_data = f.read()
        soup = BeautifulSoup(chapter_data, 'html.parser')

        title = soup.h3.getText()
        chapter = list(filter(lambda x: x['chapter_number'] == chapter_index, story_index_data['chapters']))[0]
        if title != chapter['title']:
            print('title mismatch:')
            print('... found', title)
            print('... expected', chapter['title'])
            print('... in', story_cache_path, f'({i}.txt)')
        
        chapter_text = chapter_soup_to_text(soup)
        with open(chapter_cache_path, 'w', encoding='utf8') as f:
            f.write(chapter_text)


def get_epub_chapters(epub_path, expected_chapters):
    try:
        pub = ebooklib.epub.read_epub(epub_path)
    except:
        return None
    
    chapters = []
    for item in pub.toc:
        if item.href == 'toc.html':
            # fimfiction's epubs are really screwed up...
            chapters = []
            continue
        chapters.append(item.uid)

    items = dict([(x.id, x) for x in pub.get_items()])

    try:
        chapter_items = [items[x] for x in chapters]
        return chapter_items
    except:
        print('id mismatch between epub toc and chapters')
        return None


def cache_epub_chapters(epub_chapters, story_cache_path):
    for chapter_index, chapter in enumerate(epub_chapters):
        cache_path = os.path.join(story_cache_path, f'{chapter_index}.txt')
        if os.path.exists(cache_path):
            continue

        cache = epub_item_to_text(chapter)
        with open(cache_path, 'w', encoding='utf8') as output:
            output.write(cache)
    

def epub_item_to_text(item):
    soup = BeautifulSoup(item.get_content(), 'html.parser')
    chapter_text = chapter_soup_to_text(soup)
    return chapter_text

def chapter_soup_to_text(soup):
    clean_story(soup)
    chapter_text = soup.getText().strip()
    chapter_text = re.sub(r'\n{4}\n*', '\n'*4, chapter_text)
    return chapter_text


def clean_story(soup):
    # for h1 in soup.findChildren('h1'):
        # print(h1.getText())
    for div in soup.findChildren('div', {'id': 'authors-note'}):
        h1 = div.previous_sibling
        while h1.name != 'h1':
            h1 = h1.previous_sibling
        assert h1.getText() == "Author's Note"
        h1.decompose()
        div.decompose()
    for img in soup.findChildren('img'):
        img.decompose()
    for h1 in soup.findChildren('h1'):
        h1.decompose()
        break
    for h2 in soup.findChildren('h2'):
        h2.decompose()
        break
    for h3 in soup.findChildren('h3'):
        h3.decompose()
        break
    for p in soup.findChildren('p'):
        br = soup.new_tag("br")
        p.insert_before(br)
    for br in soup.findChildren('br'):
        br.replace_with("\n")

 
    

STORY_FILTER_CUSTOMIZATIONS = r'''
%import common.ESCAPED_STRING

flag : CATEGORY ":" pattern -> categorized_tag
     | pattern              -> standalone_tag             
CATEGORY : "character" | "genre" | "series" | "content" | "warning"
?pattern : PATTERN
         | ESCAPED_STRING -> esc_string
PATTERN : /\w[\w ]*/

?feature : ".ratio"      -> ratio_feature
        | ".status"     -> status_feature
        | ".likes"      -> likes_feature
        | ".dislikes"   -> dislikes_feature
        | ".wordcount"  -> wordcount_feature
        | "max" "(" feature_list ")" -> max
        | "min" "(" feature_list ")" -> min
        | json_feature
'''

@v_args(inline=True)
class StoryFilter(QueryFilter):
    def __init__(self, archive):
        self.archive = archive
        super().__init__(STORY_FILTER_CUSTOMIZATIONS, archive.stories_by_id)
    
    def esc_string(self, string):
        return ast.literal_eval(string)
    
    def standalone_tag(self, tag):
        result = set()
        pattern = tag.lower()

        found_match = False
        for tag_name, tag_ids in self.archive.tags_by_name.items():
            if pattern in tag_name:
                found_match = True
                for id in tag_ids:
                    result.update(self.archive.stories_by_tag[id])

        if not found_match:
            print(f'warning: no match for tag pattern {pattern}')
        
        return result
    
    def categorized_tag(self, category, tag):
        result = set()
        category = category.lower()
        pattern = tag.lower()

        if category not in self.archive.tags_by_type:
            print(f'warning: {category} is not a valid tag type... use one of {self.archive.tags_by_type.keys()}')
            return result

        relevant_tags = self.archive.tags_by_type[category]

        found_match = False
        for tag_id, tag_name in self.archive.tags_by_type[category].items():
            if pattern in tag_name:
                found_match = True
                result.update(self.archive.stories_by_tag[tag_id])
    
        if not found_match:
            print(f'warning: no match for tag pattern {category}:{pattern}')
        
        return result
    
    def status_feature(self):
        return lambda x: x['completion_status']
    
    def likes_feature(self):
        return lambda x: x['num_likes']
    
    def dislikes_feature(self):
        return lambda x: x['num_dislikes']
    
    def ratio_feature(self):
        return lambda x: max(x['num_likes'], 0.5) / max(x['num_dislikes'], 0.5)
    
    def wordcount_feature(self):
        return lambda x: x['num_words']
    
    def max(self, args):
        return lambda x: max(*[f(x) for f in args])
    
    def min(self, args):
        return lambda x: min(*[f(x) for f in args])


TAG_FILTER_CUSTOMIZATIONS = r'''
%import common.ESCAPED_STRING

flag : CATEGORY ":" pattern -> categorized_tag
     | pattern              -> standalone_tag             
?pattern : PATTERN
         | ESCAPED_STRING -> esc_string
CATEGORY : "character" | "genre" | "series" | "content" | "warning"
PATTERN : /\w[\w ]*/

?feature : json_feature
'''

@v_args(inline=True)
class TagFilter(QueryFilter):
    def __init__(self, archive):
        self.archive = archive
        super().__init__(TAG_FILTER_CUSTOMIZATIONS, archive.tags_by_id)
    
    def esc_string(self, string):
        return ast.literal_eval(string)
    
    def standalone_tag(self, tag):
        result = set()
        pattern = tag.lower()

        found_match = False
        for tag_name, tag_ids in self.archive.tags_by_name.items():
            if pattern in tag_name:
                found_match = True
                for id in tag_ids:
                    result.add(id)

        if not found_match:
            print(f'warning: no match for tag pattern {pattern}')
        
        return result
    
    def categorized_tag(self, category, tag):
        result = set()
        if category not in self.archive.tags_by_type:
            print(f'warning: {category} is not a valid tag type... use one of {self.archive.tags_by_type.keys()}')
            return result

        relevant_tags = self.archive.tags_by_type[category]
        pattern = tag.lower()

        found_match = False
        for tag_id, tag_name in self.archive.tags_by_type[category].items():
            if pattern in tag_name:
                found_match = True
                result.add(tag_id)
    
        if not found_match:
            print(f'warning: no match for tag pattern {category}:{pattern}')
        
        return result
