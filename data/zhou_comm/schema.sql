PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE pages (
  print_page INTEGER PRIMARY KEY,
  pdf_page INTEGER NOT NULL,
  chapter TEXT,
  text TEXT NOT NULL,
  checksum TEXT NOT NULL,
  n_chars INTEGER NOT NULL
);

CREATE TABLE paragraphs (
  id TEXT PRIMARY KEY,              -- 冻结：zhou.p{print_page:03d}.s{seq:02d}
  print_page INTEGER NOT NULL REFERENCES pages(print_page),
  seq INTEGER NOT NULL,             -- 页内从 1
  char_start INTEGER NOT NULL,
  char_end INTEGER NOT NULL,
  text TEXT NOT NULL,
  kind TEXT NOT NULL,               -- body|formula|caption|example|footnote|header
  UNIQUE (print_page, seq)
);

CREATE VIRTUAL TABLE paragraphs_fts USING fts5(
  text,
  content='paragraphs',
  content_rowid='rowid',
  tokenize='trigram'
);

CREATE TABLE atoms (
  id TEXT PRIMARY KEY,              -- zhou.ch{N}.{slug} 稳定、可 diff，禁止 UUID
  type TEXT NOT NULL,               -- definition|theorem|formula|procedure|caveat|example
  name TEXT NOT NULL,
  statement TEXT NOT NULL,          -- 可独立阅读的陈述，但必须有 span
  chapter INTEGER NOT NULL,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  created_day INTEGER NOT NULL
);

CREATE TABLE atom_spans (
  atom_id TEXT NOT NULL REFERENCES atoms(id),
  paragraph_id TEXT NOT NULL REFERENCES paragraphs(id),
  role TEXT NOT NULL,               -- core|context|counterexample
  PRIMARY KEY (atom_id, paragraph_id)
);

CREATE TABLE atom_l3 (
  atom_id TEXT NOT NULL REFERENCES atoms(id),
  l3_id TEXT NOT NULL,              -- 必须已存在于 syllabus_comm.json
  confidence REAL NOT NULL,         -- 0–1；<0.6 进 issues，不算覆盖
  PRIMARY KEY (atom_id, l3_id)
);

CREATE TABLE terms (
  term TEXT NOT NULL,
  atom_id TEXT NOT NULL REFERENCES atoms(id),
  PRIMARY KEY (term, atom_id)
);

CREATE INDEX ix_para_page ON paragraphs(print_page);
CREATE INDEX ix_atom_ch ON atoms(chapter);
CREATE INDEX ix_l3 ON atom_l3(l3_id);
CREATE INDEX ix_terms_term ON terms(term);
