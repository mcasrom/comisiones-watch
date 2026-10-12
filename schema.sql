-- Vigilancia de comisiones parlamentarias (Congreso, Senado, mixtas)
-- SQLite para empezar; portable a PostgreSQL cambiando las funciones de fecha.

PRAGMA foreign_keys = ON;

-- Cada descarga se guarda cruda y con hash, para poder reprocesar y auditar.
CREATE TABLE IF NOT EXISTS raw_snapshots (
  id          INTEGER PRIMARY KEY,
  source      TEXT NOT NULL,           -- senado | congreso | bocg | transparencia_*
  url         TEXT NOT NULL,
  fetched_at  TEXT NOT NULL,           -- ISO 8601 UTC
  sha256      TEXT NOT NULL,
  path        TEXT NOT NULL,           -- fichero en disco con el cuerpo
  UNIQUE (url, sha256)
);

CREATE TABLE IF NOT EXISTS commissions (
  id             INTEGER PRIMARY KEY,
  chamber        TEXT NOT NULL CHECK (chamber IN ('congreso','senado','mixta')),
  kind           TEXT NOT NULL CHECK (kind IN
                   ('investigacion','permanente','legislativa','especial','mixta','subcomision','ponencia')),
  name           TEXT NOT NULL,
  source_id      TEXT,                 -- id interno en la web de origen
  created_on     TEXT,                 -- acuerdo de creación (Pleno)
  constituted_on TEXT,                 -- sesión constitutiva
  closed_on      TEXT,
  url            TEXT,
  UNIQUE (chamber, name)
);

CREATE TABLE IF NOT EXISTS members (
  id        INTEGER PRIMARY KEY,
  full_name TEXT NOT NULL,
  party     TEXT,
  UNIQUE (full_name)
);

-- role: presidente | vicepresidente | secretario | portavoz | portavoz_adjunto | vocal
CREATE TABLE IF NOT EXISTS memberships (
  id            INTEGER PRIMARY KEY,
  commission_id INTEGER NOT NULL REFERENCES commissions(id),
  member_id     INTEGER NOT NULL REFERENCES members(id),
  role          TEXT NOT NULL,
  start_date    TEXT NOT NULL,
  end_date      TEXT,
  source_url    TEXT
);

-- kind: constitucion | tramite | comparecencia | debate | otra
-- Una sesión "de fondo" es la que tiene comparecientes o debate real.
CREATE TABLE IF NOT EXISTS sessions (
  id            INTEGER PRIMARY KEY,
  commission_id INTEGER NOT NULL REFERENCES commissions(id),
  session_date  TEXT NOT NULL,
  kind          TEXT NOT NULL,
  agenda_text   TEXT,
  source_url    TEXT,
  UNIQUE (commission_id, session_date, kind)
);

CREATE TABLE IF NOT EXISTS appearances (
  id         INTEGER PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  person     TEXT NOT NULL,
  capacity   TEXT
);

-- Complemento mensual por cargo, con vigencia. Cada fila debe llevar su fuente.
CREATE TABLE IF NOT EXISTS pay_rates (
  id          INTEGER PRIMARY KEY,
  chamber     TEXT NOT NULL,
  role        TEXT NOT NULL,
  monthly_eur REAL NOT NULL,
  valid_from  TEXT NOT NULL,
  valid_to    TEXT,
  source_url  TEXT NOT NULL
);

-- Actividad por comisión.
CREATE VIEW IF NOT EXISTS v_activity AS
SELECT c.id AS commission_id, c.chamber, c.kind, c.name, c.constituted_on,
       CAST(julianday('now') - julianday(c.constituted_on) AS INTEGER) AS days_since_constituted,
       COUNT(s.id) AS sessions_total,
       SUM(CASE WHEN s.kind IN ('comparecencia','debate') THEN 1 ELSE 0 END) AS sessions_substantive,
       MAX(s.session_date) AS last_session
FROM commissions c
LEFT JOIN sessions s ON s.commission_id = c.id
GROUP BY c.id;

-- Coste ESTIMADO: tarifa vigente al alta × meses de permanencia.
-- Aproximación: no refleja subidas de tarifa durante el periodo ni cobros reales.
CREATE VIEW IF NOT EXISTS v_cost_estimate AS
SELECT m.commission_id,
       COUNT(DISTINCT m.id) AS paid_roles,
       ROUND(SUM(r.monthly_eur *
         (julianday(COALESCE(m.end_date, date('now'))) - julianday(m.start_date)) / 30.4375), 2) AS est_eur
FROM memberships m
JOIN commissions c ON c.id = m.commission_id
JOIN pay_rates r ON r.chamber = c.chamber AND r.role = m.role
 AND r.valid_from <= m.start_date AND (r.valid_to IS NULL OR r.valid_to >= m.start_date)
GROUP BY m.commission_id;

-- Ranking: coste por sesión de fondo (NULL si no hay ninguna => máxima alerta).
CREATE VIEW IF NOT EXISTS v_ranking AS
SELECT a.chamber, a.kind, a.name, a.constituted_on, a.days_since_constituted,
       a.sessions_total, a.sessions_substantive, a.last_session,
       COALESCE(c.est_eur, 0) AS est_eur,
       CASE WHEN a.sessions_substantive > 0
            THEN ROUND(c.est_eur / a.sessions_substantive, 2) END AS eur_per_substantive
FROM v_activity a
LEFT JOIN v_cost_estimate c ON c.commission_id = a.commission_id;
