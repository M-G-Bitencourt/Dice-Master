-- ============================================================================
-- 1. Matrizes Fundacionais e Catálogos Independentes
-- ============================================================================

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

CREATE TABLE "items" (
    "item_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "name" TEXT NOT NULL,
    "weight" REAL DEFAULT 0.0,
    "cost" REAL DEFAULT 0.0,
    "description" TEXT
);


CREATE TABLE "melee_weapons" (
    "melee_weapon_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "name" TEXT NOT NULL,
    "tl" INTEGER DEFAULT 0,              -- Nível Tecnológico (NT)
    "min_st" INTEGER DEFAULT 0,          -- ST Mínimo necessário
    "is_two_handed" INTEGER DEFAULT 0,   -- 1 se requer 2 mãos (marcação † ou ‡ no ST)
    "weight" REAL DEFAULT 0.0,           -- Peso (kg)
    "cost" REAL DEFAULT 0.0,             -- Custo ($)
    "description" TEXT                   -- Notas gerais
);

CREATE TABLE "melee_weapon_modes" (
    "mode_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "melee_weapon_id" INTEGER NOT NULL,
    "mode_name" TEXT DEFAULT 'Padrão',   -- Ex: 'Corte', 'Estocada', 'Gancho'
    "skill_name" TEXT NOT NULL,          -- Ex: 'Maça/Machado', 'Espada Curta'
    "damage_base" TEXT NOT NULL,         -- 'GeB' (Swing) ou 'GdP' (Thrust)
    "damage_modifier" INTEGER DEFAULT 0, -- Modificador numérico (ex: +2, -1, 0)
    "damage_type" TEXT NOT NULL,         -- 'corte', 'perfuração', 'contusão'
    "reach" TEXT NOT NULL,               -- 'C', '1', '1,2'
    "parry" TEXT NOT NULL,               -- '0', '0U' (desequilibrada), 'Não'
    "notes" TEXT,                        -- Ex: 'Gancho', 'Presa'
    FOREIGN KEY("melee_weapon_id") REFERENCES "melee_weapons"("melee_weapon_id") ON DELETE CASCADE
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

-- Catálogo de Partes do Corpo (Multiplicadores de Cobertura e Alvo de Impacto)
CREATE TABLE "body_parts" (
    "body_part_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "name" TEXT NOT NULL UNIQUE,          -- Ex: 'Cabeça', 'Tronco', 'Braços', 'Pernas', 'Mãos', 'Pés'
    "cost_weight_factor" REAL NOT NULL,   -- Multiplicador decimal (Ex: Tronco = 1.0, Cabeça = 0.30, Braços = 0.50)
    "hit_location_roll" TEXT,             -- Ponto de Impacto nos dados (Ex: '3-5', '9-11', '8, 12')
    "notes" TEXT                          -- Observações do sistema (Ex: sub-áreas, proteções parciais)
);

-- Catálogo de Materiais de Armadura (Baseados em 100% de Cobertura / Tronco)
CREATE TABLE "armor_materials" (
    "material_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "name" TEXT NOT NULL,                 -- Ex: 'Couro Médio', 'Cota de Malha Pesada', 'Placas Média'
    "tl" INTEGER DEFAULT 0,               -- Nível Tecnológico (NT)
    "dr" INTEGER NOT NULL,                -- Resistência a Dano (RD)
    "is_flexible" INTEGER DEFAULT 0,      -- 1 para RD flexível (*), 0 para armadura rígida
    "cost_torso" REAL NOT NULL,           -- Custo base de referência para o Tronco ($)
    "weight_torso" REAL NOT NULL,         -- Peso base de referência para o Tronco (kg)
    "don_time" INTEGER DEFAULT 30,        -- Tempo para vestir (segundos)
    "notes" TEXT                          -- Ex: '-1 RD contra dano por perfuração', 'Combustível'
);

-- ============================================================================
-- 2. Entidades Dependentes do Personagem (Com Cascata Estrita)
-- ============================================================================

CREATE TABLE "next_turn_conditions" (
    "character_id" INTEGER PRIMARY KEY,
    "aim" INTEGER,
    "evaluate" INTEGER,
    "shock" INTEGER,
    "feint" INTEGER,
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE
);

-- ============================================================================
-- 3. Entidades Orbitais de Magia
-- ============================================================================

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

-- ============================================================================
-- 4. Tabelas Associativas Múltiplas (Com Cascata Estrita)
-- ============================================================================

CREATE TABLE "character_skills" (
    "character_skill_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "character_id" INTEGER NOT NULL,
    "skill_id" INTEGER NOT NULL,
    "relative_level" INTEGER,
    UNIQUE("character_id", "skill_id"),
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE,
    FOREIGN KEY("skill_id") REFERENCES "skills"("skill_id") ON DELETE CASCADE
);

CREATE TABLE "character_additional_stats" (
    "character_additional_stat_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "character_id" INTEGER NOT NULL,
    "additional_stat_id" INTEGER NOT NULL,
    UNIQUE("character_id", "additional_stat_id"),
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE,
    FOREIGN KEY("additional_stat_id") REFERENCES "additional_stats"("id_additional_stat") ON DELETE CASCADE
);

CREATE TABLE "character_magics" (
    "character_magic_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "character_id" INTEGER NOT NULL,
    "magic_id" INTEGER NOT NULL,
    "relative_level" INTEGER,
    UNIQUE("character_id", "magic_id"),
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE,
    FOREIGN KEY("magic_id") REFERENCES "magics"("magic_id") ON DELETE CASCADE
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

CREATE TABLE "character_melee_weapons" (
    "character_melee_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "character_id" INTEGER NOT NULL,
    "melee_weapon_id" INTEGER NOT NULL,
    "custom_name" TEXT,                  -- Ex: 'Foice de Guerra de Titânio'
    "quantity" INTEGER DEFAULT 1,
    "is_equipped" INTEGER DEFAULT 0,
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE,
    FOREIGN KEY("melee_weapon_id") REFERENCES "melee_weapons"("melee_weapon_id") ON DELETE RESTRICT
);

CREATE TABLE "character_ranged_weapons" (
    "character_ranged_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "character_id" INTEGER NOT NULL,
    "ranged_weapon_id" INTEGER NOT NULL,
    "quantity" INTEGER DEFAULT 1,
    "current_shots" INTEGER DEFAULT 0,
    "is_equipped" INTEGER DEFAULT 0,
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE,
    FOREIGN KEY("ranged_weapon_id") REFERENCES "ranged_weapons"("ranged_weapon_id") ON DELETE CASCADE
);

-- Inventário Modular de Peças de Armadura do Personagem
CREATE TABLE "character_armors" (
    "character_armor_id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "character_id" INTEGER NOT NULL,
    "material_id" INTEGER NOT NULL,
    "body_part_id" INTEGER NOT NULL,
    "custom_name" TEXT,                   -- Nome opcional personalizado (Ex: 'Elmo de Batalha', 'Grevas de Infantaria')
    "quantity" INTEGER DEFAULT 1,
    "is_equipped" INTEGER DEFAULT 0,
    FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE,
    FOREIGN KEY("material_id") REFERENCES "armor_materials"("material_id") ON DELETE RESTRICT,
    FOREIGN KEY("body_part_id") REFERENCES "body_parts"("body_part_id") ON DELETE RESTRICT
);