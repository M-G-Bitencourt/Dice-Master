-- 1. Matrizes Fundacionais (Entidades Independentes)

CREATE TABLE "additional_stats" (
    "id_additional_stat" INTEGER PRIMARY KEY AUTOINCREMENT,
    "stat" TEXT UNIQUE
);

CREATE TABLE "skills" (
    "skill_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "name" TEXT,
    "attribute" TEXT,
    "modifier" INTEGER,
    "difficulty" TEXT,
    "description" TEXT
);

CREATE TABLE "characters" (
    "character_id" INTEGER PRIMARY KEY,
    "owner_id" INTEGER,
    "is_npc" INTEGER DEFAULT 0,
    "name" TEXT,
    "st" INTEGER DEFAULT 10,
    "dx" INTEGER DEFAULT 10,
    "iq" INTEGER DEFAULT 10,
    "ht" INTEGER DEFAULT 10,
    "additional_max_pv" INTEGER DEFAULT 0,
    "additional_vont" INTEGER DEFAULT 0,
    "additional_per" INTEGER DEFAULT 0,
    "additional_max_pf" INTEGER DEFAULT 0,
    "additional_basic_speed" INTEGER DEFAULT 0,
    "additional_basic_move" INTEGER DEFAULT 0,
    "energy_reserve" INTEGER DEFAULT 0,
    "normal_diffuse_homogeneous_unded" INTEGER DEFAULT 0,
    "money" INTEGER DEFAULT 0
);

CREATE TABLE "hdm" (
    "id_player" INTEGER PRIMARY KEY,
    "fate" INTEGER NOT NULL
);

CREATE TABLE "current_attacks" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "raw_damage" INTEGER,
    "dmg_type" INTEGER,
    "hit_location" INTEGER,
    "feint" INTEGER,
    "critical_damage" INTEGER
);

-- 2. Entidades Dependentes do Personagem (Com Cascata Estrita)

CREATE TABLE "next_turn_conditions" (
    "character_id" INTEGER PRIMARY KEY,
    "aim" INTEGER,
    "evaluate" INTEGER,
    "shock" INTEGER,
    "feint" INTEGER,
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE
);

CREATE TABLE "character_resource_pools" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "character_id" INTEGER,
    "resource" TEXT,
    "value" INTEGER,
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE
);

-- 3. Entidades Orbitais de Magia

CREATE TABLE "magics" (
    "magic_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "name" TEXT,
    "attribute" TEXT,
    "modifier" INTEGER,
    "difficulty" TEXT,
    "cost" INTEGER,
    "resource_id" TEXT,
    "description" TEXT
);

-- 4. Tabelas Associativas Múltiplas (Com Cascata Estrita)

CREATE TABLE "character_skills" (
    "character_skill_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "character_id" INTEGER,
    "skill_id" INTEGER,
    "relative_level" INTEGER,
    UNIQUE("character_id", "skill_id"),
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE,
    FOREIGN KEY("skill_id") REFERENCES "skills"("skill_id") ON DELETE CASCADE
);

CREATE TABLE "character_additional_stats" (
    "character_additional_stat_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "character_id" INTEGER,
    "additional_stat_id" INTEGER,
    UNIQUE("character_id", "additional_stat_id"),
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE,
    FOREIGN KEY("additional_stat_id") REFERENCES "additional_stats"("id_additional_stat") ON DELETE CASCADE
);

CREATE TABLE "character_magics" (
    "character_magic_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "character_id" INTEGER,
    "magic_id" INTEGER,
    "relative_level" INTEGER,
    UNIQUE("character_id", "magic_id"),
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE,
    FOREIGN KEY("magic_id") REFERENCES "magics"("magic_id") ON DELETE CASCADE
);