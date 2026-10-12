# Como coloquei o Smart Park na internet (GitHub + Render)

Com isso, qualquer celular abre o sistema por um link `https://...onrender.com`, sem precisar estar na mesma rede do notebook. Uso para testar o fluxo inteiro fingindo ser um carro (`/carro`) e para mostrar à banca.

## O que roda de verdade no servidor
| Etapa do fluxograma | No servidor do Render |
|---|---|
| Sensor de presença (HC-SR04) | simulado pelo botão "Parei na cancela" |
| Leitura da placa | **real**: a foto vai para o servidor e passa por OpenCV + Tesseract |
| Consulta ao cadastro, visitantes, LGPD | **real** (SQLite) |
| Previsão de demanda | **real** (Random Forest treinado no build) |
| Escolha da vaga (A* + Greenshields) | **real** |
| Comandos ao ESP32 (MQTT) | barramento em memória; com `SMARTPARK_BROKER`, vão para o Wokwi de verdade |
| Tablet, painel, app do corredor, admin | **reais** |
| Sensor da vaga | simulado pelo botão "Estacionei" (ou pelas chaves do Wokwi) |

## 1. Subir o projeto para o GitHub
O jeito mais simples é o **GitHub Desktop** (ele envia também os arquivos ocultos `.gitignore` e `.dockerignore`, que o Finder esconde):
1. Crio a conta em github.com e instalo o GitHub Desktop.
2. *File → Add local repository* → escolho a pasta **Smart Park TCC** → ele oferece *create a repository* → aceito.
3. *Publish repository* (pode ser privado).

Pelo Terminal, se preferir:
```bash
cd "caminho/da/pasta/Smart Park TCC"
git init && git add . && git commit -m "Smart Park"
git branch -M main
git remote add origin https://github.com/MEU_USUARIO/smartpark.git
git push -u origin main
```

## 2. Criar o serviço no Render
1. Entro em render.com com a conta do GitHub.
2. **New + → Blueprint** → escolho o repositório. O Render lê o `render.yaml`.
3. Ele pede o valor de `SMARTPARK_SENHA_ADMIN`: escolho a senha da área administrativa (mínimo 4 dígitos).
4. **Apply**. A primeira construção leva uns 5 a 10 minutos (instala o Tesseract, as bibliotecas e treina o preditor).
5. Quando aparecer *Live*, o endereço fica no topo da página, algo como `https://smartpark-xxxx.onrender.com`.

## 3. Testar como se eu fosse um carro
- No **celular**: `https://.../carro`
- No **notebook**: `https://.../equipe` (painel) e `https://.../guarita` (tela do motorista)
- Em outro celular: `https://.../corredor` (funcionário do corredor)

Imprimo `docs/placas_teste/placas_teste.pdf` (ou abro um dos PNGs em outra tela) e fotografo com o celular na página `/carro`:

| Placa | Quem é no cadastro de demonstração | O que deve acontecer |
|---|---|---|
| UDA4H28 | Dona Maria, idosa | vaga de idoso perto do templo |
| SIZ0Y20 | Lúcia, PcD | vaga PcD perto do templo |
| QTA8G91 | Ana, membro | vaga comum no setor C |
| NBA1G29 | Pr. Carlos, equipe | corredor do fundo |
| TCC2A26 | ninguém | entra como visitante (setor A); pode tocar "Sou PcD" |

Também testo "Simular placa ilegível" e estacionar numa vaga diferente da indicada (o painel avisa).

## 4. Opcional: ligar o Wokwi
Em *Environment* do serviço, crio `SMARTPARK_BROKER = broker.hivemq.com` e salvo (o Render reinicia). O servidor passa a usar a maquete de 6 vagas e a conversar com o ESP32 simulado: ao tocar "Parei na cancela" no celular, o servo do Wokwi abre e o LED da vaga pisca.

## Cuidados
- **Plano gratuito:** o serviço dorme depois de 15 minutos sem acesso; o primeiro acesso depois disso leva cerca de 1 minuto. Antes da apresentação, abro o link uns minutos antes.
- **Os dados voltam ao início** a cada reinício ou nova versão (o disco do plano gratuito não é permanente). Para teste, é o que eu quero.
- **O link é público:** os botões de simulação ficam acessíveis a quem tiver o endereço. Não divulgo o link e uso apenas placas de teste, nunca placas reais.
- Para atualizar: faço `git push` (ou *Push origin* no GitHub Desktop) e o Render publica a versão nova sozinho.
