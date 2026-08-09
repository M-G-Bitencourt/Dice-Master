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
    "money" INTEGER DEFAULT 0,
    "current_pv" INTEGER DEFAULT 0,
    "current_pf" INTEGER DEFAULT 0,
    "current_er" INTEGER DEFAULT 0,
    "current_points" INTEGER DEFAULT 0
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

CREATE TABLE "items" (
    "item_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "name" TEXT NOT NULL,
    "weight" REAL DEFAULT 0.0,
    "cost" REAL DEFAULT 0.0,
    "description" TEXT
);

CREATE TABLE "character_items" (
    "character_item_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "character_id" INTEGER NOT NULL,
    "item_id" INTEGER NOT NULL,
    "quantity" INTEGER DEFAULT 1,
    "is_equipped" INTEGER DEFAULT 0,
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE,
    FOREIGN KEY("item_id") REFERENCES "items"("item_id") ON DELETE CASCADE
);

CREATE TABLE "melee_weapons" (
    "melee_weapon_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "name" TEXT NOT NULL,
    "damage_modifier" TEXT,      -- Ex: 'st+2', 'st-1'
    "damage_type" TEXT,          -- Ex: 'corte', 'perfuração', 'contusão'
    "reach" TEXT,                -- Alcance (Ex: 'C', '1', '1,2')
    "parry" TEXT,                -- Aparar (Ex: '0', '0U', 'Não')
    "min_st" INTEGER DEFAULT 0,  -- ST Mínimo necessário
    "weight" REAL DEFAULT 0.0,   -- Peso em kg / lbs
    "cost" REAL DEFAULT 0.0,     -- Custo / Preço
    "description" TEXT
);

CREATE TABLE "ranged_weapons" (
    "ranged_weapon_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "name" TEXT NOT NULL,
    "damage" TEXT,               -- Ex: '2d+1 pi+', '3d dth'
    "acc" INTEGER DEFAULT 0,     -- Acurácia (Acc)
    "range_half" INTEGER,        -- Alcance 1/2D
    "range_max" INTEGER,         -- Alcance Máximo
    "rof" INTEGER DEFAULT 1,     -- Cadência de Tiro (RoF)
    "shots" TEXT,                -- Tiros/Carga (Ex: '10(3)', '1')
    "min_st" INTEGER DEFAULT 0,  -- ST Mínimo
    "recoil" INTEGER DEFAULT 1,  -- Recuo (Rcl)
    "weight" REAL DEFAULT 0.0,   -- Peso
    "cost" REAL DEFAULT 0.0,     -- Custo
    "description" TEXT
);

CREATE TABLE "armors" (
    "armor_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "name" TEXT NOT NULL,
    "dr" INTEGER DEFAULT 0,      -- Resistência a Dano (RD / Damage Resistance)
    "location" TEXT,             -- Local de Cobertura (Ex: 'Tronco', 'Cabeça', 'Braços')
    "weight" REAL DEFAULT 0.0,   -- Peso
    "cost" REAL DEFAULT 0.0,     -- Custo
    "description" TEXT
);

-- Inventário de Armas Corpo a Corpo do Personagem
CREATE TABLE "character_melee_weapons" (
    "character_melee_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "character_id" INTEGER NOT NULL,
    "melee_weapon_id" INTEGER NOT NULL,
    "quantity" INTEGER DEFAULT 1,
    "is_equipped" INTEGER DEFAULT 0,
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE,
    FOREIGN KEY("melee_weapon_id") REFERENCES "melee_weapons"("melee_weapon_id") ON DELETE CASCADE
);

-- Inventário de Armas a Distância do Personagem
CREATE TABLE "character_ranged_weapons" (
    "character_ranged_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "character_id" INTEGER NOT NULL,
    "ranged_weapon_id" INTEGER NOT NULL,
    "quantity" INTEGER DEFAULT 1,
    "current_shots" INTEGER DEFAULT 0, -- Tiros restantes na arma
    "is_equipped" INTEGER DEFAULT 0,
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE,
    FOREIGN KEY("ranged_weapon_id") REFERENCES "ranged_weapons"("ranged_weapon_id") ON DELETE CASCADE
);

-- Inventário de Armaduras do Personagem
CREATE TABLE "character_armors" (
    "character_armor_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "character_id" INTEGER NOT NULL,
    "armor_id" INTEGER NOT NULL,
    "quantity" INTEGER DEFAULT 1,
    "is_equipped" INTEGER DEFAULT 0,
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE,
    FOREIGN KEY("armor_id") REFERENCES "armors"("armor_id") ON DELETE CASCADE
);