# Como vou coletar as chegadas reais

O simulador ainda usa as minhas hipóteses de volume e de horário de chegada. Para os resultados representarem a igreja de verdade, vou contar as chegadas reais.

**O que registro:** só o horário em que cada carro passa pela entrada. Não anoto placa, modelo nem pessoa.

**Como:** um voluntário fica na guarita com um aplicativo de contador com horário (ou uma planilha no celular), de 50 minutos antes até 20 minutos depois do início do culto.

**Quanto:** pelo menos 4 ocorrências de cada um dos 4 cultos, o que dá cerca de 1 mês. Anoto também chuva, feriado ou evento especial.

**Formato do arquivo** (`chegadas_reais.csv`):

```
culto_idx,ocorrencia,t_min
1,2026-11-08,-14.5
1,2026-11-08,-13.9
```

`culto_idx`: 0 = Domingo 8h30, 1 = Domingo 11h, 2 = Domingo 17h, 3 = Domingo 19h30. `t_min`: minutos em relação ao início do culto (negativo = antes).

**Como uso os dados:**
```bash
python -m simulador.treinar_preditor --csv chegadas_reais.csv
```
Depois ajusto os perfis em `simulador/chegadas.py` (volume médio, pico, dispersão) com as médias observadas e rodo o experimento de novo.

Também vou cronometrar a manobra de uns 20 carros, do momento em que param ao lado da vaga até liberarem o corredor. Hoje o simulador assume de 12 a 24 s.
