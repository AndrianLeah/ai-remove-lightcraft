<p align="center">
  <img src="assets/icon/airemove-256.png" width="128" alt="Icona di AI Remove: un procione inciso">
</p>

<h1 align="center">AI Remove 2.0 beta</h1>

<p align="center"><b>AI locale per le app Craft: toglie oggetti, persone e riflessi dalle foto, sul tuo computer.</b></p>

[English](README.md)

> **Questa è la 2.0 beta,** nel branch `openai-server`, e non è ancora uscita. La versione attuale è la 1.6, il
> plug-in per LightCraft e Chromaforge ([il suo README](https://github.com/AndrianLeah/ai-remove-lightcraft/blob/main/README.it.md)).
> Chi ha la 1.x non riceve la beta dal controllo degli aggiornamenti.

AI Remove 2.0 è un **fornitore di AI locale per il livello AI comune delle app Craft,**
[craft-ai-integrations](https://github.com/storytold/craft-ai-integrations). In quel livello colleghi un'app Craft a
un servizio di AI, per esempio con una chiave OpenAI. AI Remove si collega allo stesso modo, come server compatibile
con OpenAI, ma gira sul tuo computer. Gli strumenti delle app per togliere e riempire possono così usare LaMa, RORem,
FLUX Fill, Qwen-Image e DAI sulla tua scheda video:
- senza account;
- senza costi per immagine;
- senza che nessuna foto esca dal tuo computer.

Tutto quello che fa la 1.x c'è ancora. [La finestra di AI Remove](#la-finestra-di-ai-remove) si apre da LightCraft o
da Chromaforge con Ctrl/Cmd+Shift+X, oppure da sola, e da un RAW scrive un DNG RAW.

> AI Remove è **non ufficiale**: non è fatto, sponsorizzato né approvato dal team di ArtCraft (storytold), che sviluppa
> le app Craft e craft-ai-integrations, né da chi sviluppa Chromaforge.

## Come funziona la 2.0

```
App Craft: uno strumento per togliere o riempire
   │  l'immagine, una maschera (e un prompt)
   ▼
craft-ai-integrations: una connessione personalizzata compatibile con OpenAI
   │  POST http://127.0.0.1:7990/v1/images/edits
   ▼
AI Remove (airemove-cli --serve): LaMa, RORem, FLUX Fill, Qwen-Image, DAI sulla tua GPU
   │  tutta l'immagine, delle stesse dimensioni, cambiata solo dove c'è la maschera
   ▼
di nuovo nell'app
```

1. [Installa](#installazione) AI Remove e i modelli che vuoi.
2. [Avvia il server](#avviare-il-server): `airemove-cli --serve`.
3. [Collegalo](#collegarlo-a-unapp-craft): nella configurazione AI delle app Craft aggiungi una connessione
   personalizzata compatibile con OpenAI verso `http://127.0.0.1:7990/v1` e dichiara i suoi modelli.

Dietro ogni richiesta c'è lo stesso lavoro della finestra:
- gli stessi modelli;
- lo stesso modo di preparare l'area;
- le aree lunghe riempite a tasselli lungo l'oggetto;
- la stessa fusione invisibile.

**Pixel, non il RAW.** L'app manda la foto come la mostra, e riceve indietro dei pixel. Riscrivere il risultato nel
RAW, come DNG con i dati della fotocamera, resta compito della finestra:
- l'API per le immagini di OpenAI non ha posto per un RAW;
- l'adattatore OpenAI del livello Craft manda solo PNG, JPEG o WebP.

Come una rimozione resti non distruttiva su un RAW lo decide poi l'app.

## A che punto è

- **Fatto in questa beta:**
  - il server, i suoi modelli e la sua sicurezza;
  - un test CI dall'inizio alla fine, con le richieste costruite come le costruisce l'adattatore OpenAI di
    craft-ai-integrations;
  - ogni modello provato su foto vere.
- **Non ancora provato:** dentro un'app Craft. craft-ai-integrations è il livello comune che i suoi sviluppatori
  stanno costruendo per le app Craft; quale app lo usa, e quando, lo decidono loro.
- **In attesa di craft-ai-integrations:**
  - Il suo strumento *Remove objects* è quello indicato per "Rimozione generativa" di LightCraft e per lo strumento
    Rimuovi di PhotoCraft. Manda un'immagine e una maschera senza prompt, ma oggi il livello chiede un prompt ai
    modelli di una connessione personalizzata. I modelli di AI Remove compariranno lì quando per loro il prompt sarà
    facoltativo. La modifica è stata proposta a chi sviluppa il livello.
  - È stato proposto anche uno strumento per i riflessi, per i modelli `dai-…`.
  - Il suo adattatore rifiuta un'immagine di risposta oltre i 32 MiB. Un PNG li supera intorno ai 30 megapixel, quindi
    per le foto più grandi l'app dovrebbe chiedere `output_format` `webp` o `jpeg`. In alternativa, l'adattatore
    potrebbe consegnare i risultati grandi come file, come fa il suo adattatore per ComfyUI.

## Avviare il server

```bash
~/AIRemove/venv/bin/airemove-cli --serve --port 7990 --key-file ~/airemove-server.key
```

Su Windows: `%USERPROFILE%\AIRemove\venv\Scripts\airemove-cli.exe --serve`. `--port` (7990 se non lo indichi) e
`--key-file` sono facoltativi. Quando è in ascolto scrive una riga JSON con il suo indirizzo e i modelli che questo
computer può usare. Si ferma con Ctrl+C.

- **La chiave:** con `--key-file` ogni richiesta deve avere `Authorization: Bearer <chiave>`, dove la chiave è il
  contenuto del file. Tieni il file dove puoi leggerlo solo tu. La chiave non va mai sulla riga di comando, dove altri
  programmi potrebbero vederla.
- **Memoria:** i modelli restano caricati sulla scheda video tra una richiesta e l'altra; per liberarla, ferma il
  server. Gira una richiesta alla volta, e le altre aspettano.

## Collegarlo a un'app Craft

Nella configurazione di craft-ai-integrations aggiungi una **connessione personalizzata compatibile con OpenAI**:

| Campo | Valore |
|---|---|
| Nome | AI Remove |
| Indirizzo del server | `http://127.0.0.1:7990/v1` (l'HTTP semplice è accettato per l'indirizzo di questo computer) |
| Identificativo del fornitore | `ai-remove` |
| Chiave | quella del tuo file della chiave, o nessuna |
| Modelli | `lama`, `rorem`, `flux` e `qwen`, dichiarati come **inpainting di immagini**; `dai-50`, `dai-75`, `dai-100` e `dai-125`, dichiarati come **modifica di immagini** |

Il **Test** della connessione elenca i modelli: `GET /v1/models` risponde con quelli installati che possono girare su
questo computer. Con una chiave, il Test chiede una volta anche senza, e il rifiuto del server conferma che la chiave
viene controllata.

## I modelli

| Modello | Id nel server | Quando usarlo | Non per | Peso | Licenza |
|---|---|---|---|---|---|
| **LaMa** | `lama` | Oggetti piccoli e medi su sfondi semplici (muro, cielo, prato, asfalto). Gira sul processore, un solo risultato in pochi secondi. | Aree grandi e strutture (porte, finestre): le sfoca | 0,2 GB | Apache-2.0 |
| **RORem** (con i file di SDXL Inpainting) | `rorem` | Persone e oggetti, il modello predefinito: SDXL riaddestrato solo per togliere; dove SDXL ridisegna una persona o un oggetto strano nel buco, disegna lo sfondo. Circa 7 s a variante con una GPU. | Buchi lunghi e sottili (un palo): può lasciare una giuntura, LaMa o FLUX sono più puliti | 11,6 GB (SDXL 6,8 + RORem 4,8) | Apache-2.0, su CreativeML Open RAIL++-M di SDXL |
| **FLUX Fill + Turbo** | `flux` | Il più realistico: rispetta luce, prospettiva e architettura. Per aree grandi o difficili. Serve una GPU da 12 GB o più. | Le persone: in una strada o tra la folla ridisegna persone dove c'erano | 16,4 GB | FLUX.1 [dev] Non-Commercial |
| **Qwen-Image 2.1 Turbo** (facoltativo) | `qwen` | Persone e oggetti su sfondi complessi (una persona davanti a una scalinata, un palo davanti alle colonne): riconosce cosa c'è da togliere e lo toglie chiamandolo per nome. Circa 30 s a variante a 1024 px. Serve una GPU NVIDIA o AMD da 16 GB. | Quando hai fretta: circa un minuto per la prima variante di una rimozione | 14,4 GB | Qwen Research License (non commerciale); il suo encoder del testo Qwen3-VL: Apache-2.0 |
| **DAI** (facoltativo) | `dai-50`, `dai-75`, `dai-100`, `dai-125`: quanto del riflesso trovato viene tolto | I riflessi nel vetro: su tutta l'immagine o su un'area con la maschera, in pochi secondi con una GPU; il riflesso si toglie dai valori dei pixel, niente viene ridisegnato | Riempire qualcosa; un riflesso nitido e luminoso (alberi specchiati in una vetrina, il cielo in una pozzanghera) si toglie solo in parte | 5,7 GB | Apache-2.0, ritocco di Stable Diffusion 2 (CreativeML Open RAIL++-M) |
| **SAM 3** | (la finestra) | La selezione con un clic, o descrivendo cosa selezionare ("people"). Senza, si usa il pennello. | | 3,2 GB, oppure 0 GB se è già in LightCraft o in Chromaforge | SAM License (Meta) |
| **OSOR** (facoltativo, su FLUX) | (la finestra) | Trova le ombre e i riflessi accanto a ciò che selezioni, per "Includi l'ombra" (insieme a SAM 3). | | 0,6 GB | FLUX.1 [dev] Non-Commercial |

**Il prompt.**
- **Attraverso il server,** il prompt della richiesta va a FLUX ("old plaster wall", "dark doorway"). LaMa, RORem e
  Qwen-Image lo ignorano: Qwen-Image dà da solo il nome a ciò che toglie.
- **Nella finestra,** il testo facoltativo **in inglese** guida FLUX. Con Qwen-Image dice cosa togliere, se il modello
  lo ha riconosciuto male ("the lamp post").

**Modelli tolti.**
- **SDXL Inpainting** non è più nel menu: ridisegnava una persona o un oggetto strano dove RORem non ne ridisegnava
  nessuno (11 rimozioni di prova su 12, contro 0). RORem, che usa i suoi file, fa il suo lavoro.
- **ObjectClear** non c'è più: a 512 px i suoi riempimenti erano sempre morbidi, e "Includi l'ombra" con RORem o FLUX
  fa lo stesso più nitido. L'aggiornamento toglie la sua cartella dai modelli di AI Remove (7,3 GB).
- **OSOR** non è più un modello del menu: trova le ombre per "Includi l'ombra".

I progetti tengono le varianti fatte con questi modelli, e `--auto sdxl` / `--auto osor` funzionano ancora.

**Uso commerciale.** FLUX, OSOR e Qwen-Image sono solo per uso non commerciale. Vanno bene per le tue foto, ma non per
lavori pagati o per clienti senza una licenza dei loro autori: Black Forest Labs per FLUX e OSOR, il team Qwen di
Alibaba per Qwen-Image. Per i lavori pagati usa LaMa o RORem (con le limitazioni d'uso di SDXL), e DAI per i riflessi
(con quelle di Stable Diffusion 2). La licenza di FLUX chiede anche di controllare i risultati prima di condividerli, e
di dire che sono stati modificati con l'AI dove la legge lo richiede. È un riassunto, non un parere legale: valgono le
licenze.

## L'API del server

`airemove-cli --serve` risponde a una piccola parte dell'API per le immagini di OpenAI.

| Richiesta | Risposta |
|---|---|
| `GET /v1/models` | i modelli che questo computer può usare, nell'elenco come lo dà OpenAI |
| `POST /v1/images/edits` | l'immagine modificata |
| `GET /health` | `{"ok": true, "version": …}` |

Gli indirizzi funzionano anche senza `/v1`.

- **La richiesta** è `POST /v1/images/edits` in multipart/form-data, come quella di OpenAI, con questi campi:
  - `model`;
  - `image`, o il primo `image[]` (PNG, JPEG o WebP; la trasparenza resta);
  - `mask`;
  - `prompt`;
  - `n` (da 1 a 4 varianti; LaMa e DAI ne danno sempre una);
  - `output_format`: `png` (se non lo indichi), `jpeg` o `webp`;
  - `output_compression`: la qualità di un JPEG o di un WebP, da 0 a 100 (100 se non la indichi; un WebP a 100 è
    senza perdita).
- **La risposta** è `{"created": …, "output_format": …, "data": [{"b64_json": …}]}`: tutta l'immagine, delle stesse
  dimensioni, uguale fuori dalla rimozione (a parte la perdita propria di un JPEG o di un WebP con perdita). I link
  (`response_format=url`) non ci sono.
- **Quanto pesa la risposta:**
  - un PNG occupa circa 1,1 byte per pixel: circa 17 MiB per una foto da 13 megapixel;
  - un WebP senza perdita occupa circa un quarto in meno;
  - un JPEG a 95 occupa circa un quarto del PNG.
- **La maschera** segue la convenzione di OpenAI quando ha la trasparenza: trasparente = l'area da cambiare.
  Altrimenti bianco = l'area. Una maschera di altre dimensioni viene adattata all'immagine. I modelli che riempiono
  ne vogliono una; DAI senza maschera lavora su tutta l'immagine.
- **Gli errori** hanno la forma di quelli di OpenAI, `{"error": {"message", "type", "param", "code"}}`. I codici sono
  `missing_mask`, `invalid_mask`, `model_not_found` e `invalid_api_key`, e lo stato HTTP dice il resto (403, 404, 411,
  413).
- **Limiti:**
  - immagini fino a 100 megapixel, a 8 bit per canale;
  - richieste fino a 256 MiB;
  - un lavoro alla volta, sulla scheda video: gli altri aspettano. I modelli restano caricati tra un lavoro e l'altro.
- **Tempi** per una foto da 13 megapixel su una scheda AMD da 16 GB, caricamento del modello compreso:
  - LaMa: circa 20 s;
  - DAI: circa 25 s;
  - RORem: circa 45 s;
  - FLUX e Qwen-Image: circa un minuto.
- **Sicurezza:**
  - ascolta solo su 127.0.0.1;
  - risponde solo alle richieste indirizzate a `127.0.0.1:<porta>` o `localhost:<porta>`, così una pagina web non può
    raggiungerlo cambiando l'indirizzo di un sito;
  - non risponde alle richieste delle pagine web (quelle con un `Origin`);
  - con `--key-file` vuole la chiave, confrontata in tempo costante.

## Cosa serve

| | |
|---|---|
| **Per il server** | nessun'altra app. Per usarlo da un'app serve un'app Craft con craft-ai-integrations, o un programma che sa usare le modifiche di immagini di OpenAI |
| **Per la finestra** | **LightCraft** o **Chromaforge**, o tutti e due: servono per Ctrl/Cmd+Shift+X e per i RAW; JPEG, PNG, TIFF, WebP, HEIC e AVIF si aprono anche senza (vedi [LightCraft e Chromaforge](#lightcraft-e-chromaforge)) |
| **Windows 10/11** | scheda NVIDIA, AMD Radeon RX 7000/9000 o Intel Arc; senza GPU funziona solo LaMa |
| **macOS 12+** | Mac con chip Apple (M1 o successivi); meglio con almeno 16 GB di memoria |
| **Linux x86-64** | scheda NVIDIA, oppure AMD con ROCm |
| **Spazio su disco** | da 5 GB (solo LaMa) a circa 30 GB (tutti i modelli) |
| **Internet** | durante l'installazione; poi solo un controllo di nuove versioni su GitHub, al massimo una volta al giorno (non invia nulla su di te o sulle foto; si spegne con `"update_check": false` in `work/settings.json`) |

## Installazione

La 2.0 non ha ancora un pacchetto: scarica questo branch, poi avvia l'installer del tuo sistema.

```bash
git clone -b openai-server https://github.com/AndrianLeah/ai-remove-lightcraft.git
```

- **Windows**: `Install on Windows.cmd`. Se compare "Windows ha protetto il PC", scegli *Ulteriori informazioni* >
  *Esegui comunque*. Lo script non è firmato.
- **Mac**: lo script non è firmato da Apple, quindi il doppio clic viene bloccato ("sviluppatore non identificato").
  Il modo più semplice:
  1. apri il **Terminale** (Applicazioni > Utility);
  2. scrivi `sh ` (con lo spazio dopo);
  3. trascina `Install on Mac.command` nella finestra e premi Invio.

  In alternativa: doppio clic, poi *Impostazioni di Sistema > Privacy e sicurezza > Apri comunque* (chiede la
  password). Su macOS 15 il vecchio "clic destro > Apri" non basta più. Quello che l'installer scarica dopo e l'app
  "AI Remove" che crea si aprono normalmente.
- **Linux**: in un terminale, `sh "Install on Linux.sh"`.

Hai già la 1.x? Avvialo sulla stessa cartella: aggiorna il programma e tiene i modelli che hai.

L'installer:

1. riconosce la scheda video;
2. ti chiede quale app configurare per la finestra: LightCraft, Chromaforge, entrambe, o nessuna (basta per usare solo
   il server);
3. ti chiede quali modelli installare, mostrando a cosa serve ciascuno, quanto pesa e la sua licenza. Se un modello
   ce l'hai già sul disco, puoi indicare la sua cartella invece di riscaricarlo (vedi sotto);
4. scarica Python e PyTorch nella cartella `AIRemove` della tua home;
5. crea il programma "AI Remove" con la sua icona (menu Start, Applicazioni o menu delle app);
6. configura ogni app scelta: ne attiva il canale di controllo, imposta AI Remove come editor esterno e assegna la
   scorciatoia.

Ci vogliono da 10 minuti a un'ora, quasi tutto per i download.

**Dopo l'installazione riavvia l'app una volta**: legge l'impostazione del canale di controllo solo all'avvio.

Se l'app era aperta, l'installer ti chiede di chiuderla per scrivere le impostazioni. Puoi anche ripetere solo
questo passaggio più tardi (per esempio dopo aver installato Chromaforge), con
`installer/bootstrap.ps1 --configure-lightcraft` su Windows o `installer/bootstrap.sh --configure-lightcraft` su Mac e
Linux; `--apps lightcraft|chromaforge|both` sceglie senza domande.

Senza domande, solo per il server: `--yes --models lama,rorem,dai --apps none`.

### SAM 3 e FLUX: token di Hugging Face

- **SAM 3** è lo stesso modello delle maschere *Oggetto* di LightCraft e di Chromaforge. Se una delle due l'ha già
  scaricato, AI Remove usa quella copia e non scarica niente.
- **FLUX**, e SAM 3 se nessuna delle due app ce l'ha, hanno una licenza da accettare su Hugging Face:
  1. crea un account gratuito su [huggingface.co](https://huggingface.co);
  2. accetta la licenza sulla pagina del modello:
     [facebook/sam3](https://huggingface.co/facebook/sam3),
     [black-forest-labs/FLUX.1-Fill-dev](https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev);
  3. crea un token di tipo *Read* su [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) e
     incollalo quando l'installer lo chiede.

Senza SAM 3 la selezione si fa col pennello, oppure con una maschera chiamata "Rimuovi" (o "Remove") fatta in LightCraft
o in Chromaforge.

### Modelli che hai già

Se un modello è già sul tuo disco, alla sua domanda rispondi con la cartella invece di *s*: puoi trascinarla nella
finestra dell'installer. Va bene:

- un'altra installazione di AI Remove, o la sua cartella `models`;
- la cache di Hugging Face (`~/.cache/huggingface/hub`), dove i modelli stanno in cartelle `models--<autore>--<nome>`;
- la cartella `models` di ComfyUI (il GGUF di FLUX in `models/unet`);
- la cartella del modello stesso.

L'installer guarda anche qualche livello più sotto, controlla i file come fa l'app e ti dice cosa ha trovato. Quello che
lì non c'è lo scarica: per esempio gli encoder di testo di FLUX, se in ComfyUI c'è solo il suo GGUF. Quello che trova
lo usa dov'è: non copia niente, e disinstallare AI Remove non tocca quella cartella. Le cartelle restano scritte in
`airemove.json` (`model_paths`), quindi non spostarle.

Senza domande: `--model-dir flux=D:\ComfyUI\models --model-dir rorem=~/.cache/huggingface/hub`.

## La finestra di AI Remove

Tutto quello che fa la 1.x, uguale nella 2.0.

### Come funziona la finestra

1. In LightCraft o in Chromaforge scegli una foto e premi **Ctrl+Shift+X** (**Cmd+Shift+X** su Mac).
2. Nella finestra di AI Remove clicca su ciò che vuoi togliere: SAM 3 lo seleziona tutto. Oppure **descrivilo**:
   scrivi "people" (in inglese) e SAM 3 seleziona tutte le persone della foto, anche quelle lontane (guarda la foto
   intera e a riquadri). Ogni persona è selezionata per conto suo, così con un clic destro togli dalla selezione
   quella che vuoi tenere.
3. Seleziona tutto in una volta, descrivendo quante volte vuoi ("person", poi "bag", poi "sign") e correggendo con
   pennello e gomma. Per togliere anche l'ombra o il riflesso degli oggetti, premi **Includi l'ombra**: li aggiunge
   alla selezione, in blu. Le ombre che li toccano le trova SAM 3, anche quelle lunghe del sole basso; OSOR, se c'è,
   trova anche i riflessi.
4. **Dividi in parti** taglia la selezione in parti della misura giusta per i modelli:
   - le cose lontane tra loro (una persona a sinistra, un cartello a destra) diventano parti separate, numerate sulla
     foto;
   - una folla, o una persona con la sua ombra, resta una sola parte, finché la sua area resta abbastanza piccola
     perché i modelli la disegnino nitida. Una folla più grande diventa più parti, riempite una dopo l'altra.

   Seleziona ogni parte, scegli il suo modello e premi **Genera**, oppure **Genera tutte** per le altre. Il menu dice
   per cosa va bene ciascun modello, e per cosa no: FLUX Fill ridisegna persone in mezzo alla folla. Per ogni parte
   scegli la variante migliore. **Rimuovi selezione** fa tutto in un colpo, con un solo modello per tutte le parti.
   - Ogni parte vede quelle prima già riempite.
   - Pali, cavi e cordoni lunghi vengono riempiti a tasselli lungo l'oggetto, ognuno vicino alla misura del modello:
     il riempimento resta nitido invece di essere un'immagine piccola ingrandita. Per quelli sottili si aggiunge una
     variante LaMa, che continua meglio ciò che c'è dietro.
   - **Dettaglio pieno** ridisegna la variante scelta alla risoluzione della foto.
5. Premi **Salva in LightCraft** o **Salva in Chromaforge** (il pulsante dice l'app da cui viene la foto). Da un RAW il
   risultato è un **DNG RAW** (`<nome>-AIRemove.dng`), impilato sopra l'originale e con lo stesso sviluppo: puoi
   continuare a svilupparlo come un RAW qualsiasi. Da un JPEG è `<nome>-AIRemove.jpg`, e così per gli altri formati.

**Riflessi nel vetro.** Per una foto attraverso una vetrina o una teca, scegli **DAI** sotto *Rimuovi riflessi* nel
menu dei modelli e premi **Rimuovi riflessi**. Senza selezione lavora su tutta la foto, con una selezione solo lì,
sfumando intorno. Come "Rimuovi riflessi" di Lightroom, toglie la luce che il vetro riflette (la strada vista nella
vetrina, il velo su ciò che sta dietro). La toglie dai valori del RAW stesso: niente viene ridisegnato, e restano ogni
dettaglio e il rumore del sensore. **Intensità**, sotto il risultato, dice quanto toglierne (da 0 a 150 %, 75 %
all'inizio), e la foto segue mentre trascini.

Ogni rimozione resta modificabile: la puoi rigenerare, cambiare variante o eliminare in qualsiasi momento. Tutto è
salvato in un unico file accanto alla foto (`<foto>.airemove`). L'originale non viene mai modificato.

**Da sola.** La finestra funziona anche su una foto che non è in nessuna delle due app. Apri AI Remove dal menu Start,
da Applicazioni o dal menu delle app con le app chiuse (o senza una foto selezionata), e ti chiede un file; **Apri
foto…** nella finestra ne apre un'altra. **Salva come DNG** (o **Salva come JPEG**…) scrive il risultato accanto alla
foto, senza importarlo da nessuna parte.
- **Un RAW:** LightCraft o Chromaforge deve essere installato, non aperto. AI Remove legge il RAW con la sua riga di
  comando, con il suo sviluppo predefinito.
- **Un JPEG, PNG, TIFF, WebP, HEIC o AVIF:** si apre così com'è, senza nessuna delle due app.

**Le immagini normali** tengono quello che avevano: il profilo colore, l'EXIF e l'XMP. Dall'EXIF si toglie solo la
piccola anteprima, che mostrerebbe ancora ciò che hai rimosso.
- **Il JPEG** si salva con le stesse impostazioni di compressione dell'originale: fuori dalla rimozione i pixel si
  spostano di un livello o due, in modo invisibile.
- **PNG, TIFF e WebP senza perdita** si salvano senza perdita; i TIFF a 16 bit restano a 16 bit.
- **L'HEIC** perde la mappa di profondità e le altre immagini aggiuntive.
- Un PNG a colori a 16 bit, un'immagine CMYK o animata non si apre (il messaggio dice cosa fare).

### Comandi

| | Windows / Linux | Mac |
|---|---|---|
| Seleziona un oggetto | clic | clic |
| Seleziona tutti gli esemplari di qualcosa | scrivilo sotto gli strumenti ("people"), Invio | scrivilo sotto gli strumenti ("people"), Invio |
| Togli una parte / aggiungi una parte | Alt+clic / Shift+clic | Option+clic / Shift+clic |
| Pennello / Gomma / Clic SAM | B / E / S | B / E / S |
| Dimensione di Pennello / Gomma | Alt+rotella, `+` `−` oppure `[` `]` | Option+rotella, `+` `−` oppure `[` `]` |
| Elimina un oggetto dalla selezione | clic destro | clic destro (o Ctrl+clic) |
| Zoom | Ctrl+rotella, Ctrl+`+` `−` (`+` `−` da soli con Clic SAM), `0` = adatta | Cmd+rotella, Cmd+`+` `−` (`+` `−` da soli con Clic SAM), `0` = adatta |
| Sposta la vista | rotella, tasto centrale, Spazio+trascina | due dita, Spazio+trascina |
| Annulla | Ctrl+Z | Cmd+Z |
| Confronta con l'originale | tieni premuto "Originale" o `\` | tieni premuto "Originale" o `\` |
| Rimuovi selezione | Invio | Invio |
| Ferma la generazione (le varianti già fatte restano) | Esc | Esc |
| Variante precedente / successiva | ← / → | ← / → |
| Elimina una variante | clic destro sulla variante | clic destro (o Ctrl+clic) sulla variante |

AI Remove si può aprire anche dal menu Start, da Applicazioni o dal menu delle app. Lavora sulla foto attiva di
LightCraft o di Chromaforge se uno dei due è aperto, altrimenti su una foto che scegli tu (vedi "Da sola" sopra). Su
Mac puoi anche trascinare una foto sulla sua icona.

### Dove finiscono i file

- `<nome>-AIRemove.dng` (da un'immagine: `.jpg`, `.png`… come l'originale): la foto ritoccata, nella cartella
  dell'originale e impilata con lui in LightCraft o in Chromaforge (da sola: solo nella cartella).
- `<nome della foto>.airemove`: il progetto, con tutte le rimozioni e le varianti, accanto alla foto. Con un doppio
  clic apre la foto in AI Remove.
- `~/AIRemove`: il programma, i modelli, i log (`install.log` e `work/last-run.log`).

Il server non scrive niente accanto alle tue foto: risponde con l'immagine, e i suoi file temporanei vengono
cancellati dopo ogni richiesta.

### LightCraft e Chromaforge

[Chromaforge](https://github.com/emmertex/lightcraft-classic) (prima "LightCraft Classic") è un fork di
[LightCraft](https://github.com/storytold/lightcraft) con l'impostazione di Lightroom Classic. La finestra funziona
allo stesso modo in tutti e due:
- Ctrl/Cmd+Shift+X;
- il risultato impilato sull'originale;
- le maschere chiamate "Rimuovi" come selezione di partenza;
- SAM 3 in comune con le maschere Oggetto dell'app.

Cambia solo il modo in cui AI Remove parla con ciascuna:

| | LightCraft | Chromaforge |
|---|---|---|
| Dove si scarica | [getartcraft.com](https://getartcraft.com) | [le sue release](https://github.com/emmertex/lightcraft-classic/releases) |
| Canale di controllo | porta 7980, `LIGHTCRAFT_CONTROL_PORT` | porta 7981, `LIGHTCRAFT_CLASSIC_CONTROL_PORT` |
| Password sul canale | nessuna | un token che l'app scrive nella sua cartella delle impostazioni a ogni avvio (`control-token-<porta>`); AI Remove lo legge da lì |
| Cartella delle impostazioni (Windows) | `%APPDATA%\LightCraft` | `%APPDATA%\LightCraft Classic` |
| Riga di comando, per un RAW aperto da solo | `lightcraft-cli` | `lightcraft-classic-cli` (usata se LightCraft non è installato) |

L'installer ti chiede quale configurare: **LightCraft, Chromaforge o entrambi** (quelli installati sono la risposta
predefinita); `--apps` risponde senza domanda.
- **Tutti e due aperti:** con due porte diverse possono essere aperti insieme. AI Remove chiede a ciascuna app aperta
  quale foto ha selezionato, così Ctrl/Cmd+Shift+X apre la foto dell'app in cui l'hai premuto.
- **Avviato dal menu con tutti e due aperti:** prende la foto attiva di LightCraft (di Chromaforge se in LightCraft non
  ce n'è); `--app chromaforge` prende quella di Chromaforge.
- **Hai installato Chromaforge dopo?** Ripeti la configurazione: `--configure-lightcraft --apps chromaforge`.

**Il modello Soggetto di Chromaforge, se lo installi.** Chromaforge può usare BiRefNet per le maschere Soggetto e
Sfondo. Su Windows e Linux gira sul processore: circa 10 secondi ogni volta che va ridisegnata una foto con una di
queste maschere (anche quelle "Seleziona soggetto" di Lightroom, importate dagli XMP), e AI Remove lo aspetta quando
legge quella foto. Per spegnerlo, chiudi Chromaforge e rinomina la cartella `models\birefnet` nella sua cartella
delle impostazioni (per esempio in `birefnet.disabled`): quelle maschere useranno di nuovo l'analisi rapida dell'app.

## Lingua

La finestra di AI Remove è in **inglese** e in **italiano**. Di base segue la lingua di LightCraft, altrimenti quella
di Chromaforge. Puoi sceglierla dal pulsante in alto a destra nella finestra (`EN ▾` / `IT ▾`); vale dalla volta dopo
che apri AI Remove. Per forzarla si usa la variabile `AIREMOVE_LANG=it` oppure `AIREMOVE_LANG=en`. Le risposte e gli
errori del server sono in inglese, come quelli di OpenAI.

## Con un assistente AI (MCP)

La cartella `mcp/` contiene un server MCP. Permette a un assistente AI (Claude, Cursor, VS Code...) di:

- controllare il computer e spiegare cosa verrà scaricato;
- installare AI Remove e configurarlo per LightCraft e/o Chromaforge;
- aprirlo o rimuovere oggetti senza finestra.

La configurazione è descritta in [mcp/README.md](mcp/README.md). Gli agenti con accesso al terminale trovano le
istruzioni in [AGENTS.md](AGENTS.md), anche quelle per avviare il server.

## Aggiornare e disinstallare

- **Aggiornare**: rilancia l'installer della nuova versione. Tiene ciò che c'è già e non riscarica i modelli.
- **Disinstallare**:
  - Windows: *Impostazioni > App > AI Remove for LightCraft and Chromaforge*;
  - Mac: `Uninstall AI Remove.command` nella cartella `AIRemove`;
  - Linux: `uninstall.sh` nella cartella `AIRemove`.

  La disinstallazione toglie il programma, i modelli e le impostazioni aggiunte a LightCraft e Chromaforge. Le foto, i
  DNG creati e i progetti `.airemove` restano. La connessione personalizzata nella configurazione AI delle app Craft
  la togli tu.

## Problemi frequenti

- **Il server non parte: "cannot listen on 127.0.0.1:7990"**: un altro programma usa già quella porta (o un altro
  server di AI Remove è già aperto). Scegline un'altra con `--port` e mettila anche nell'indirizzo della connessione.
- **La connessione risponde 401**: la chiave nella connessione non è quella del file passato a `--key-file`.
- **"LightCraft non risponde"** o **"Chromaforge non risponde"**: l'app è chiusa oppure è stata aperta prima
  dell'installazione. Riavviala. Su Linux con Wayland la sua finestra deve essere visibile.
- **"Chromaforge non ha accettato AI Remove"**: il token del suo canale di controllo non è quello che AI Remove ha
  letto. Chiudi Chromaforge e riaprilo.
- **Aprire una foto da Chromaforge è lento**: probabilmente hai installato il suo modello Soggetto (BiRefNet), che su
  Windows e Linux gira sul processore. Vedi [LightCraft e Chromaforge](#lightcraft-e-chromaforge) per spegnerlo.
- **La prima variante è lenta (AMD)**: la GPU compila i suoi programmi la prima volta che incontra una dimensione,
  poi va veloce.
- **Mac: "Python vorrebbe accedere a…"**: se i RAW sono su un disco esterno, sulla Scrivania o in Documenti, macOS
  chiede una volta il permesso. Rispondi *Consenti*.
- **Memoria della GPU esaurita**: usa RORem invece di FLUX, oppure meno varianti, e chiudi gli altri programmi che
  usano la GPU (anche il server, se è aperto: tiene i modelli caricati).
- **LightCraft o Chromaforge in Flatpak (Linux)**: l'installer dà all'app i permessi necessari: rete locale, cartella
  `AIRemove`, avvio di programmi esterni. Si possono togliere con
  `flatpak override --user --reset ai.storyteller.lightcraft` (LightCraft) o
  `flatpak override --user --reset com.emmertex.chromaforge` (Chromaforge).

## Privacy e sicurezza

Le foto non lasciano mai il computer. Dopo l'installazione l'unica richiesta a internet è il controllo giornaliero
di nuove versioni (vedi sopra).

**Il server** è attivo solo mentre lo fai girare, e solo per questo computer:
- ascolta su 127.0.0.1;
- non risponde né alle pagine web né alle richieste indirizzate a un altro nome;
- con `--key-file` risponde solo ai programmi che mandano la sua chiave.

Senza chiave, mentre gira, qualunque programma sul tuo computer può usarlo.

**La finestra**, per parlare con LightCraft e con Chromaforge, usa i loro canali di controllo, raggiungibili solo dal
tuo computer (127.0.0.1):
- **quello di LightCraft** (porta 7980) è **senza password**: mentre LightCraft è aperto, qualunque programma sul tuo
  computer può comandarlo;
- **quello di Chromaforge** (porta 7981) vuole un token che l'app scrive nella sua cartella delle impostazioni: lo
  possono usare solo i programmi che leggono quella cartella.

La disinstallazione li disattiva.

## Licenze

Il codice di AI Remove è distribuito con licenza MIT ([LICENSE.txt](LICENSE.txt)). I modelli hanno le loro licenze e
vengono scaricati dalle loro fonti, non sono inclusi nel pacchetto: i dettagli sono in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
