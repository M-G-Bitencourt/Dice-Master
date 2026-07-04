CREATE TABLE "additional_stats" (
	"id_additional_stat"	INTEGER NOT NULL UNIQUE,
	"stat"	TEXT UNIQUE,
	PRIMARY KEY("id_additional_stat" AUTOINCREMENT)
);
CREATE TABLE "skills" (
	"skill_id"	INTEGER NOT NULL UNIQUE,
	"name"	TEXT,
	"attribute"	TEXT,
	"modifier"	INTEGER,
	"difficulty"	TEXT,
	"description"	TEXT,
	PRIMARY KEY("skill_id" AUTOINCREMENT)
);
CREATE TABLE "magics" (
	"magic_id"	INTEGER NOT NULL UNIQUE,
	"name"	TEXT,
	"attribute"	TEXT,
	"modifier"	INTEGER,
	"difficulty"	TEXT,
	"cost"	INTEGER,
	"resource" TEXT,
	"description"	TEXT,
	PRIMARY KEY("magic_id" AUTOINCREMENT)
);
CREATE TABLE "characters" (
	"character_id"	INTEGER PRIMARY KEY AUTOINCREMENT,
	"owner_id"	INTEGER,
	"is_npc"	INTEGER DEFAULT 0,
	"name"	TEXT,
	"st"	INTEGER DEFAULT 10,
	"dx"	INTEGER DEFAULT 10,
	"iq"	INTEGER DEFAULT 10,
	"ht"	INTEGER DEFAULT 10,
	"additional_max_pv"	INTEGER DEFAULT 0,
	"additional_vont"	INTEGER DEFAULT 0,
	"additional_per"	INTEGER DEFAULT 0,
	"additional_max_pf"	INTEGER DEFAULT 0,
	"additional_basic_speed"	INTEGER DEFAULT 0,
	"additional_basic_move"	INTEGER DEFAULT 0,
	"energy_reserve"	INTEGER DEFAULT 0
);
CREATE TABLE "character_additional_stats" (
	"character_additional_stat_id" INTEGER PRIMARY KEY AUTOINCREMENT,
	"character_id"	INTEGER,
	"additional_stat_id"	INTEGER,
	FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE,
	FOREIGN KEY("additional_stat_id") REFERENCES "additional_stats"("additional_stat_id") ON DELETE CASCADE,
	UNIQUE("character_id", "additional_stat_id")
);
CREATE TABLE "character_skills" (
	"character_skill_id" INTEGER PRIMARY KEY AUTOINCREMENT,
	"character_id"	INTEGER,
	"skill_id"	INTEGER,
	FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE,
	FOREIGN KEY("skill_id") REFERENCES "skills"("skill_id") ON DELETE CASCADE,
	UNIQUE("character_id", "skill_id")
);
CREATE TABLE "character_magics" (
	"character_magic_id" INTEGER PRIMARY KEY AUTOINCREMENT,
	"character_id"	INTEGER,
	"magic_id"	INTEGER,
	FOREIGN KEY("character_id") REFERENCES "characters"("character_id") ON DELETE CASCADE,
	FOREIGN KEY("magic_id") REFERENCES "magic"("magic_id") ON DELETE CASCADE,
	UNIQUE("character_id", "magic_id")
);
CREATE TABLE hdm (
    id_player INTEGER PRIMARY KEY,
    fate INTEGER NOT NULL
);
CREATE TABLE "next_turn_conditions" (
	"player_id"	INTEGER,
	"aim"	INTEGER,
	"evaluate"	INTEGER,
	"shock"	INTEGER,
	"feint"	INTEGER,
	PRIMARY KEY("player_id")
);
CREATE TABLE "current_attacks" (
	"id"	INTEGER NOT NULL,
	"raw_damage"	INTEGER,
	"dmg_type"	TEXT,
	"hit_location"	TEXT,
	"feint"	INTEGER,
	PRIMARY KEY("id" AUTOINCREMENT)
);
