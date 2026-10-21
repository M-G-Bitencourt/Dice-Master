![Python](https://img.shields.io/badge/Python-3.14+-blue?logo=python&logoColor=white)

![Dice Master Banner](/assets/github_banner.png)

# Dice-Master

[Read this document in English](README.md)

O Dice Master é um bot de Discord criado para simplificar sessões de GURPS. Ele automatiza rolagens, cálculos de dano e o gerenciamento de fichas diretamente no chat.

## Idioma

O idioma padrão do bot é inglês. Em cada servidor, um administrador pode alterar o idioma com `/language`; português do Brasil e inglês estão disponíveis.

- As respostas, embeds, botões, modais e mensagens de erro usam o idioma configurado no servidor.
- Os nomes e as descrições dos slash commands são localizados pelo Discord de acordo com o idioma do cliente de cada usuário. O idioma configurado no servidor não altera o menu de comandos do cliente.
- Em clientes configurados em português, os comandos aparecem com os nomes localizados, como `/ficha`, `/inventario` e `/combate_atacar`.
- Novos idiomas podem ser adicionados criando um arquivo em `locales/`, sem alterar o código. Consulte `locales/README.md`.

## Comandos gerais

| Comando | Descrição |
| :---: | :---: |
| /help | Lista todos os comandos disponíveis e suas descrições. |

## Comandos de configuração

| Comando | Descrição |
| :---: | :---: |
| /language | Altera o idioma do bot neste servidor. |

## Comandos de combate

| Comando | Descrição |
| :---: | :---: |
| /damage | Calcula o dano de um ataque sem alterar o banco de dados. |
| /combat_aim | Executa uma manobra de mira com uma arma de combate a distância. |
| /combat_evaluate | Executa uma manobra de avaliação com uma arma corpo a corpo. |

## Comandos administrativos

| Comando | Descrição |
| :---: | :---: |
| /manage_character_resource_pool | Gerencia PV, PF e ER de todos os personagens. |
| /restore_character_resources | Restaura PV, PF e ER de um personagem aos valores máximos. |
| /switch_character | Troca o personagem ativo do jogador. |
| /manage_next_turn_conditions | Gerencia os estados de choque, avaliação, mira e finta. |
| /clear_next_turn_conditions | Remove todos os modificadores de finta, avaliação, mira e choque. |
| /view_next_turn_conditions | Exibe os modificadores de finta, mira, avaliação e choque de um personagem. |
| /manage_xp | Adiciona ou remove pontos de personagem. |

## Comandos de combate estruturado

| Comando | Descrição |
| :---: | :---: |
| /combat_start | Cria ou atualiza o painel de combate do canal atual. |
| /combat_attack | Ataca com uma arma equipada usando resolução automática de NH, dano, local de acerto e defesa. |
| /combat_feint | Executa uma disputa rápida e aplica a penalidade resultante ao próximo ataque do atacante. |
| /combat_enter | Adiciona um personagem ao combate com iniciativa; o padrão é a Velocidade Básica, preservando decimais. |
| /combat_next_turn | Avança para o próximo participante e inicia uma nova rodada quando necessário. |
| /combat_undo | Reverte o último dano aplicado no canal (somente mestre). |
| /combat_end | Encerra o combate e descarta o ataque pendente. |
| /combat_manage_effect | Adiciona ou remove um efeito do catálogo externo de um personagem; o catálogo é gerenciado externamente. |

A Fase 1 suporta armas corpo a corpo equipadas. Os ataques são publicados com botões de defesa; o alvo ou o mestre os resolve no local. Apenas um ataque pode ficar pendente por canal, e um novo ataque substitui o anterior. A armadura usa a ordem de camadas configurada. Cada camada flexível abaixo de uma camada rígida perde 1 RD, e múltiplas camadas rígidas geram um aviso para o mestre. O mestre pode substituir RD e NH pelo modal de ajuste.

A Fase 2 adiciona efeitos estruturados de um catálogo externo, usos de defesa por turno, tentativas extras de defesa, reinício de rotação de turno via `/combat_next_turn` e ações rápidas após um ataque resolvido. O bot apenas vincula ou desvincula efeitos do catálogo; recursos e custos são gerenciados externamente. Um ataque resolvido oferece `Repetir ataque`, `Mirar` e `Avaliar` ao atacante ou ao mestre. O painel de combate lista participantes e a rodada atual. Os tipos de efeito incluem modificadores ativos (`attack`, `damage`, `defense`, `dodge`, `parry`, `extra_defense_attempts`, `extra_defense_uses`), RD passiva (`rd`), resistência por HT (`ht_check`) e bônus passivos de atributos (`st`, `dx`, `iq`, `ht`, `max_pv`, `max_pf`, `will`, `per`, `basic_speed`, `basic_move`). Bônus de atributos e de resistência valem apenas nos cálculos de combate.

A Fase 3 adiciona armas a distância equipadas com expressões de dano interpretadas, como `2d+1 imp`, rastreamento de iniciativa e turno ativo, uma mensagem persistente de painel de combate, histórico de eventos no painel e reversão de dano pelo mestre. A iniciativa usa a Velocidade Básica por padrão e aceita valores decimais. Armas a distância possuem o ID da perícia necessária; os ataques verificam se o personagem possui essa perícia. Ataques a distância usam Mira em vez de Avaliação e não podem ser aparados, a menos que a mesa permita; os alvos ainda podem esquivar por padrão. Penalidades de carga se aplicam a ataques corpo a corpo, ataques a distância e fintas. Ataques desarmados são fornecidos por armas internas vinculadas a perícias desarmadas; personagens sem uma perícia desarmada específica usam os modos genéricos com padrão DX-4.

A Fase 4 começa dividindo o fluxo de combate em módulos focados e adiciona `/combat_feint`. Uma finta bem-sucedida armazena uma penalidade de defesa no atacante, consumida pelo próximo ataque dele. Fintas malsucedidas limpam as condições transitórias anteriores do atacante. Personagens entram no combate apenas por `/combat_enter`; ataques e fintas exigem que ambos os personagens sejam participantes. A defesa é resolvida pelos botões anexados a um ataque pendente, não por um slash command. O painel oferece atualização sob demanda e um botão de avançar turno exclusivo do mestre.

## Regras de dano

- Com 1/3 do PV máximo ou menos, o Deslocamento Básico e a Esquiva são reduzidos pela metade.
- Cruzar para 0 PV ou menos dispara um teste automático de HT para consciência.
- Atingir -1x, -2x, -3x e múltiplos adicionais do PV máximo dispara testes automáticos de morte.
- Falhar um teste de morte por 1 ou 2 significa estar morrendo; falhar por 3 ou mais significa estar morto.
- Com -5x o PV máximo, o personagem está morto; com -10x, o corpo é obliterado.
- Os testes são resolvidos por evento de dano e exibidos no embed de ataque ou defesa. Estados de ferimento persistentes permanecem externos ao bot.
- Os embeds de dano mostram a expressão da arma, os dados rolados, a soma dos modificadores e o dano total. A resolução da defesa mostra dano bruto, RD, dano penetrante, multiplicador e dano aplicado.
- Ferimentos causam choque no próximo turno do alvo: -1 por PV perdido, limitado a -4. Personagens com 20 ou mais PV máximo usam um ponto por `max_pv // 10` de ferimento. O choque acumula entre golpes até -4, afeta ataques e fintas baseados em DX/IQ, nunca defesas, e expira no fim do turno do personagem.

## Comandos de teste de habilidade

| Comando | Descrição |
| :---: | :---: |
| /test | Executa uma rolagem de sucesso. |
| /qkd | Resolve uma disputa rápida e retorna o vencedor. |

## Comandos de ficha

| Comando | Descrição |
| :---: | :---: |
| /sheet | Exibe sua ficha de personagem em uma mensagem efêmera. |
| /sheet_view | Exibe a ficha de qualquer personagem ou PdM para o mestre. |

## Comandos de inventário

| Comando | Descrição |
| :---: | :---: |
| /manage_money | Adiciona ou remove dinheiro de um personagem. |
| /inventory | Exibe o inventário completo. |

## Outros comandos de teste

| Comando | Descrição |
| :--- | :--- |
| /roll | Rola uma quantidade variável de d6 e retorna a soma. |
| /react | Executa uma rolagem de reação. |
| /panic | Executa uma verificação de pânico e retorna o resultado. |

## Capturas de tela

### Comandos administrativos

<p align="center">
  <img src="/assets/restore_character_resource.png" alt="Saída de /restore_character_resources" width="45%">
  <br>
  <em>Saída de `/restore_character_resources`</em>
</p>

### Comandos de teste de habilidade

<p align="center">
  <img src="/assets/test.png" alt="Rolagem de sucesso de /test" width="45%">
  <img src="/assets/quick_dispute.png" alt="Resultado de disputa rápida de /qkd" width="45%">
  <br>
  <em>Rolagem de sucesso de `/test` | resultado de disputa rápida de `/qkd`</em>
</p>

### Comandos de ficha

<p align="center">
  <img src="/assets/sheet.png" alt="Central de ficha de personagem de /sheet" width="45%">
  <br>
  <em>Central de ficha de personagem de `/sheet`</em>
</p>

### Comandos de inventário

<p align="center">
  <img src="/assets/manage_money.png" alt="Transação de /manage_money" width="45%">
  <br>
  <em>Transação de `/manage_money`</em>
</p>

### Outros comandos de teste

<p align="center">
  <img src="/assets/react.png" alt="Rolagem de reação de /react" width="45%">
  <img src="/assets/panic.png" alt="Verificação de pânico de /panic" width="45%">
  <br>
  <em>Rolagem de reação de `/react` | verificação de pânico de `/panic`</em>
</p>

As capturas acima mostram a interface no locale `pt-BR`.
