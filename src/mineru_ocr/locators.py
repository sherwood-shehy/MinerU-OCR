"""Version-bound clause locations with separate main-text/commentary namespaces."""
from __future__ import annotations

from collections import Counter
import hashlib
import re

NUMBER = r'(?:[1-9]\d?(?:\.\d+)*|[A-Z](?:\.\d+)+)'


class LocatorIndex:
    def __init__(self, source_hash: str):
        self.source_hash = source_hash
        self.partition = '前置材料'
        self.namespace = 'front'
        self.commentary = False
        self.counts = Counter()
        self.items = []
        self.issues = []

    def mark(self, value: str, page: int | None) -> str | None:
        compact = re.sub(r'\s+', '', value)
        clause = re.match(r'^(' + NUMBER + r')\s+(.+)', value)
        if clause and re.match(r'^[-—–－]', clause.group(2)):
            return None  # numbered figure legends must not reset the clause partition
        appendix = re.fullmatch(r'附录\s*([A-Z])', value)
        if compact in {'条文说明', '标准条文说明', '规范条文说明'}:
            self.commentary = True
            self.partition, self.namespace = '条文说明', 'commentary'
            key = 'commentary'
        elif compact in {'本规范用词说明', '本标准用词说明', '引用标准名录', '参考文献'}:
            self.partition, self.namespace = compact, 'supplement'
            key = 'supplement-' + hashlib.sha256(compact.encode()).hexdigest()[:12]
        elif appendix:
            letter = appendix.group(1)
            self.partition = ('条文说明·' if self.commentary else '') + '附录' + letter
            self.namespace = ('commentary-' if self.commentary else '') + 'appendix-' + letter.lower()
            key = self.namespace
        elif clause:
            number = clause.group(1)
            if number == '1' and not self.commentary:
                self.partition, self.namespace = '正文', 'body'
            if self.namespace == 'front':
                return None
            key = self.namespace + '-clause-' + number.lower().replace('.', '-')
        else:
            return None
        self.counts[key] += 1
        if self.counts[key] > 1:
            self.issues.append({'kind': 'duplicate_locator', 'partition': self.partition,
                                'title': value, 'page': page})
            key += '-occurrence-' + str(self.counts[key])
        self.items.append({'anchor': key, 'partition': self.partition,
                           'clause': clause.group(1) if clause else None, 'title': value,
                           'pdf_page': page, 'source_sha256': self.source_hash})
        return key
