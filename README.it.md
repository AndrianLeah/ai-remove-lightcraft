<p align="center">
  <img src="assets/icon/airemove-256.png" width="128" alt="Icona di AI Remove: un procione inciso">
</p>

<h1 align="center">AI Remove per LightCraft e Chromaforge</h1>

[English](README.md)

Toglie oggetti e persone dalle foto con l'intelligenza artificiale, direttamente dentro
[LightCraft](https://github.com/storytold/lightcraft) o [Chromaforge](https://github.com/emmertex/lightcraft-classic),
oppure da solo. Fa quello che in Lightroom è "Rimozione generativa", ma tutto gira sul tuo computer. Lavora sui RAW e
anche su JPEG, PNG, TIFF, WebP, HEIC e AVIF.

Funziona allo stesso modo in tutte e due le app, in una sola o in entrambe insieme: l'installer ti chiede quale
configurare (vedi [LightCraft e Chromaforge](#lightcraft-e-chromaforge)).

1. In LightCraft o in Chromaforge scegli una foto e premi **Ctrl+Shift+X** (**Cmd+Shift+X** su Mac). Su Windows si
   apre il **pannello di AI Remove** accanto alla finestra dell'app e lavora sulla maschera che selezioni nell'app (vedi
   [Il pannello](#il-pannello)). Il suo pulsante **Finestra intera** apre la finestra di AI Remove, dove si fanno i
   passi qui sotto. Su macOS e Linux si apre direttamente la finestra.
2. Nella finestra di AI Remove clicca su ciò che vuoi togliere: SAM 3 lo seleziona tutto. Oppure **descrivilo**:
   scrivi "people" (in inglese) e SAM 3 seleziona tutte le persone della foto, anche quelle lontane (guarda la foto
   intera e a riquadri), ognuna per conto suo, così con un clic destro togli dalla selezione quella che vuoi tenere.
3. Seleziona tutto in una volta, descrivendo quante volte vuoi ("person", poi "bag", poi "sign") e correggendo con
   pennello e gomma. Per togliere anche l'ombra o il riflesso degli oggetti, premi **Includi l'ombra**: li aggiunge
   alla selezione, in blu (le ombre che li toccano le trova SAM 3, anche quelle lunghe del sole basso; OSOR, se c'è,
   anche i riflessi).
4. **Dividi in parti** taglia la selezione in parti della misura giusta per i modelli: le cose lontane tra loro (una
   persona a sinistra, un cartello a destra) diventano parti separate, numerate sulla foto, mentre una folla o una
   persona con la sua ombra restano una sola, finché la loro area resta abbastanza piccola perché i modelli la
   disegnino nitida (una folla diventa più parti, riempite una dopo l'altra). Seleziona ogni parte, scegli il suo
   modello (il menu dice per cosa va bene ciascuno, e per cosa no: FLUX Fill ridisegna persone in mezzo alla folla) e
   premi **Genera**, oppure **Genera tutte** per le altre. Per ognuna scegli la variante migliore. **Rimuovi
   selezione** fa tutto in un colpo, con un solo modello per tutte le parti. Ogni parte vede quelle prima già riempite.
   Pali, cavi e cordoni lunghi vengono riempiti a tasselli lungo l'oggetto, ognuno vicino alla misura del modello:
   il riempimento resta nitido invece di essere un'immagine piccola ingrandita. Per quelli sottili si aggiunge una
   variante LaMa, che continua meglio ciò che c'è dietro. **Dettaglio pieno** ridisegna la variante scelta alla
   risoluzione della foto.
5. Premi **Salva in LightCraft** o **Salva in Chromaforge** (il pulsante dice l'app da cui viene la foto): da un RAW il
   risultato è un **DNG RAW** (`<nome>-AIRemove.dng`), impilato sopra l'originale e con lo stesso sviluppo. Puoi
   continuare a svilupparlo come un RAW qualsiasi. Da un JPEG è `<nome>-AIRemove.jpg`, e così per gli altri formati.

**Riflessi nel vetro.** Per una foto attraverso una vetrina o una teca, scegli **DAI** sotto *Rimuovi riflessi* nel
menu dei modelli e premi **Rimuovi riflessi**: senza selezione lavora su tutta la foto, con una selezione solo lì,
sfumando intorno. Come "Rimuovi riflessi" di Lightroom, toglie la luce che il vetro riflette (la strada vista nella
vetrina, il velo su ciò che sta dietro), e la toglie dai valori del RAW stesso: niente viene ridisegnato, restano ogni
dettaglio e il rumore del sensore. **Intensità**, sotto il risultato, dice quanto toglierne (da 0 a 150 %, 75 %
all'inizio), e la foto segue mentre trascini.

**Disegnare qualcosa di nuovo (riempimento generativo).** Scegli **Riempimento generativo** sotto *Disegna qualcosa di
nuovo* nel menu dei modelli, seleziona dove va, scrivi cosa disegnare in inglese ("a wooden bench", "a lemon tree in a
terracotta pot", "white clouds") e premi **Disegna nella selezione**.
- **Il modello:** FLUX Fill lo disegna con la luce e la messa a fuoco della foto.
- **Il risultato:** viene scritto nel RAW come il riempimento di una rimozione, in un DNG che si sviluppa come
  l'originale.
- **La selezione è la forma che riempie:** per qualcosa che sta in piedi, seleziona fino a terra, altrimenti galleggia.
- **Non disegna l'ombra a terra.**
- **Le selezioni grandi:** una selezione grande viene disegnata più piccola della foto e al 100 % risulta morbida. La
  nota sotto la variante dice di quanto; una selezione più piccola la disegna più nitida.

Ogni rimozione resta modificabile: la puoi rigenerare, cambiare variante o eliminare in qualsiasi momento. Tutto è
salvato in un unico file accanto alla foto (`<foto>.airemove`). L'originale non viene mai modificato.

**Da solo.** AI Remove funziona anche su una foto che non è in nessuna delle due app: aprilo dal menu Start, da
Applicazioni o dal menu delle app con le app chiuse (o senza una foto selezionata) e ti chiede un file; **Apri foto…**
nella finestra ne apre un'altra. **Salva come DNG** (o **Salva come JPEG**…) scrive il risultato accanto alla foto,
senza importarlo da nessuna parte.
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

## Il pannello

Su Windows, Ctrl+Shift+X apre un piccolo pannello agganciato alla finestra di LightCraft o di Chromaforge. Con le
maschere dell'app toglie oggetti, riempie e toglie riflessi, senza uscire dall'app.

- **Dove sta:** agganciato al bordo destro dell'app. Resta sopra l'app, e solo sopra di lei, e si sposta e si
  riduce a icona con lei. Trascinalo dalla barra in alto per metterlo altrove: la volta dopo si riapre lì. Con un
  doppio clic sulla barra torna agganciato, e **–** lo chiude a metà. Premendo di nuovo Ctrl+Shift+X torna davanti.
- **La selezione è la maschera dell'app.** Seleziona una maschera nell'app e il pannello la prende. Può essere una
  maschera Oggetto fatta con un clic del SAM 3 dell'app, un pennello, un gradiente… In *Riflessi* lavora su tutta la
  foto, come "Rimuovi riflessi" di Lightroom.
- **Le schede della finestra:**
  - **Rimuovi** ha il menu dei modelli, con ⓘ *A cosa serve*;
  - **Riempi** chiede cosa disegnare (obbligatorio);
  - **Riflessi** usa DAI, poi *Intensità* sotto il risultato.

  Invio genera, Esc ferma, ← → scorrono le varianti.
- **Il risultato si vede sulla foto nell'app.** La variante scelta viene disegnata sopra la foto, nella vista
  dell'app stessa, come sua Layout Image. Succede finché la foto si vede intera (vista Dettaglio, Adatta, non durante
  il ritaglio). Tieni premuto **Originale**, o `\`, per confrontare.
- **Una rimozione per maschera.** Ogni maschera tiene le sue varianti finché il pannello è aperto, e *Su questa foto*
  le elenca. **Salva in LightCraft** (o in Chromaforge) scrive tutte le varianti scelte in un solo DNG, impilato
  sull'originale, e il salvataggio successivo aggiorna lo stesso DNG. Le maschere usate come selezione non passano nel
  DNG.
- **Dividi in maschere.** Una maschera fatta di più pezzi, o di più clic Oggetto, diventa una maschera per parte
  nell'app ("Distractions 1", "Distractions 2"…). Ogni parte è poi una selezione con il suo modello. Gli oggetti
  vicini restano in una maschera sola, perché ognuno si vedrebbe nel riempimento dell'altro. Un solo Annulla nell'app
  torna indietro.
- **Finestra intera** apre la finestra di AI Remove sulla stessa foto. Ha le stesse rimozioni e varianti, e i modelli
  sono già caricati. Serve per quello che il pannello non fa: i clic con SAM 3, il pennello, la descrizione, *Includi
  l'ombra*, *Dividi in parti*. **Torna al pannello** riporta indietro quello che hai fatto lì.
- **Preferisci la finestra?** Nella finestra, il pulsante della lingua in alto a destra (`IT ▾`) ha *Ctrl+Shift+X in
  LightCraft apre il pannello*: togli la spunta. Su macOS e Linux è già senza spunta. Se la metti, il pannello si apre
  come una finestra normale accanto all'app.

Le app non hanno pannelli per i plug-in, quindi il pannello è una finestra a sé sopra l'app. Legge lo stato dell'app
circa ogni secondo e mezzo. L'anteprima sulla foto non viene disegnata in questi casi, e il pannello lo dice:
- con lo zoom, o durante il ritaglio;
- con una trasformazione di Geometria (Upright, prospettiva).

Il salvataggio non ne risente. La prima volta che il pannello legge una foto, il ritaglio sparisce per un attimo.

> AI Remove è un plug-in **non ufficiale**: non è fatto, sponsorizzato né approvato dal team di ArtCraft, che sviluppa
> LightCraft, né da chi sviluppa Chromaforge.

## LightCraft e Chromaforge

[Chromaforge](https://github.com/emmertex/lightcraft-classic) (prima "LightCraft Classic") è un fork di
[LightCraft](https://github.com/storytold/lightcraft) con l'impostazione di Lightroom Classic. AI Remove funziona allo
stesso modo in tutti e due: Ctrl/Cmd+Shift+X, il risultato impilato sull'originale, le maschere chiamate "Rimuovi"
come selezione di partenza, SAM 3 in comune con le maschere Oggetto dell'app. Cambia solo il modo in cui AI Remove
parla con ciascuna:

| | LightCraft | Chromaforge |
|---|---|---|
| Dove si scarica | [getartcraft.com](https://getartcraft.com) | [le sue release](https://github.com/emmertex/lightcraft-classic/releases) |
| Canale di controllo | porta 7980, `LIGHTCRAFT_CONTROL_PORT` | porta 7981, `LIGHTCRAFT_CLASSIC_CONTROL_PORT` |
| Password sul canale | nessuna | un token che l'app scrive nella sua cartella delle impostazioni a ogni avvio (`control-token-<porta>`); AI Remove lo legge da lì |
| Cartella delle impostazioni (Windows) | `%APPDATA%\LightCraft` | `%APPDATA%\LightCraft Classic` |
| Riga di comando, per un RAW aperto da solo | `lightcraft-cli` | `lightcraft-classic-cli` (usata se LightCraft non è installato) |

L'installer ti chiede quale configurare: **LightCraft, Chromaforge o entrambi** (quelli installati sono la risposta
predefinita); `--apps` risponde senza domanda. Con due porte diverse possono essere aperti tutti e due: AI Remove chiede
a ciascuna app aperta quale foto ha selezionato, così Ctrl/Cmd+Shift+X apre la foto dell'app in cui l'hai premuto.
Avviato dal menu con tutti e due aperti, prende la foto attiva di LightCraft (di Chromaforge se in LightCraft non ce
n'è); `--app chromaforge` prende quella di Chromaforge. Hai installato Chromaforge dopo? Ripeti la configurazione:
`--configure-lightcraft --apps chromaforge`.

**Il modello Soggetto di Chromaforge, se lo installi.** Chromaforge può usare BiRefNet per le maschere Soggetto e
Sfondo. Su Windows e Linux gira sul processore: circa 10 secondi ogni volta che va ridisegnata una foto con una di
queste maschere (anche quelle "Seleziona soggetto" di Lightroom, importate dagli XMP), e AI Remove lo aspetta quando
legge quella foto. Per spegnerlo, chiudi Chromaforge e rinomina la cartella `models\birefnet` nella sua cartella
delle impostazioni (per esempio in `birefnet.disabled`): quelle maschere useranno di nuovo l'analisi rapida dell'app.

## Cosa serve

| | |
|---|---|
| **LightCraft** o **Chromaforge** | installato, o tutti e due (vedi [LightCraft e Chromaforge](#lightcraft-e-chromaforge)) |
| **Windows 10/11** | scheda NVIDIA, AMD Radeon RX 7000/9000 o Intel Arc; senza GPU funziona solo LaMa |
| **macOS 12+** | Mac con chip Apple (M1 o successivi); meglio con almeno 16 GB di memoria |
| **Linux x86-64** | scheda NVIDIA, oppure AMD con ROCm |
| **Spazio su disco** | da 5 GB (solo LaMa) a circa 30 GB (tutti i modelli) |
| **Internet** | durante l'installazione; poi solo un controllo di nuove versioni su GitHub, al massimo una volta al giorno (non invia nulla su di te o sulle foto; si spegne con `"update_check": false` in `work/settings.json`) |

## Installazione

Decomprimi la cartella dove vuoi e fai doppio clic sul file del tuo sistema:

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

L'installer:

1. riconosce la scheda video;
2. ti chiede quale app configurare: LightCraft, Chromaforge o entrambi;
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

## I modelli

| Modello | Quando usarlo | Non per | Peso | Licenza |
|---|---|---|---|---|
| **LaMa** | Oggetti piccoli e medi su sfondi semplici (muro, cielo, prato, asfalto). Gira sul processore, un solo risultato in pochi secondi. | Aree grandi e strutture (porte, finestre): le sfoca | 0,2 GB | Apache-2.0 |
| **RORem** (con i file di SDXL Inpainting) | Persone e oggetti, il modello predefinito: SDXL riaddestrato solo per togliere; dove SDXL ridisegna una persona o un oggetto strano nel buco (l'altra di due persone vicine, chi porta una borsa rimasta fuori dalla selezione), disegna lo sfondo. Circa 7 s a variante con una GPU. | Buchi lunghi e sottili (un palo): può lasciare una giuntura, LaMa o FLUX sono più puliti | 11,6 GB (SDXL 6,8 + RORem 4,8) | Apache-2.0, su CreativeML Open RAIL++-M di SDXL |
| **FLUX Fill + Turbo** | Il più realistico: rispetta luce, prospettiva e architettura. Per aree grandi o difficili. Serve una GPU da 12 GB o più. Fa anche il **Riempimento generativo** (Disegna qualcosa di nuovo): quello che descrivi, disegnato nella selezione. | Le persone: in una strada o tra la folla ridisegna persone dove c'erano. Quando disegna: niente ombra a terra; le selezioni grandi vengono morbide | 16,4 GB | FLUX.1 [dev] Non-Commercial |
| **SAM 3** | La selezione con un clic, o descrivendo cosa selezionare ("people"). Senza, si usa il pennello. | | 3,2 GB, oppure 0 GB se è già in LightCraft o in Chromaforge | SAM License (Meta) |
| **OSOR** (facoltativo, su FLUX) | Trova le ombre e i riflessi accanto a ciò che selezioni, per "Includi l'ombra" (insieme a SAM 3). | | 0,6 GB | FLUX.1 [dev] Non-Commercial |
| **Qwen-Image 2.1 Turbo** (facoltativo) | Persone e oggetti su sfondi complessi (una persona davanti a una scalinata, un palo davanti alle colonne): riconosce cosa hai selezionato e lo toglie chiamandolo per nome. Circa 30 s a variante a 1024 px. Serve una GPU NVIDIA o AMD da 16 GB. | Quando hai fretta: circa un minuto per la prima variante di una rimozione | 14,4 GB | Qwen Research License (non commerciale); il suo encoder del testo Qwen3-VL: Apache-2.0 |
| **DAI** (facoltativo) | I riflessi nel vetro, "Rimuovi riflessi": su tutta la foto o su una selezione, in pochi secondi con una GPU; il riflesso si toglie dai valori del RAW, niente viene ridisegnato. **Intensità**, sotto il risultato, dice quanto toglierne, da 0 a 150 % (75 % all'inizio: il più vicino al risultato di Lightroom, misurato su una vetrina). | Riempire qualcosa; un riflesso nitido e luminoso (alberi specchiati in una vetrina, il cielo in una pozzanghera) si toglie solo in parte | 5,7 GB | Apache-2.0, ritocco di Stable Diffusion 2 (CreativeML Open RAIL++-M) |

**Modelli tolti.** SDXL Inpainting non è più nel menu: ridisegnava una persona o un oggetto strano dove RORem non ne
ridisegnava nessuno (11 rimozioni di prova su 12, contro 0), e RORem, che usa i suoi file, fa il suo lavoro. ObjectClear
non c'è più: a 512 px i suoi riempimenti erano sempre morbidi, e "Includi l'ombra" con RORem o FLUX fa lo stesso più
nitido. L'aggiornamento toglie la sua cartella dai modelli di AI Remove (7,3 GB). OSOR non è più un modello del menu:
trova le ombre per "Includi l'ombra". I progetti tengono le varianti fatte con questi modelli, e `--auto sdxl` /
`--auto osor` funzionano ancora.

**Uso commerciale.** FLUX, OSOR e Qwen-Image sono solo per uso non commerciale. Vanno bene per le tue foto, ma non per
lavori pagati o per clienti senza una licenza dei loro autori: Black Forest Labs per FLUX e OSOR, il team Qwen di
Alibaba per Qwen-Image. Per i lavori pagati usa LaMa o RORem (con le limitazioni d'uso di SDXL), e DAI per i riflessi
(con quelle di Stable Diffusion 2). La licenza di FLUX chiede anche di controllare i risultati prima di condividerli, e
di dire che sono stati modificati con l'AI dove la legge lo richiede. È un riassunto, non un parere legale: valgono le
licenze.

Il testo facoltativo **in inglese** guida il riempimento, per esempio "old plaster wall" o "dark doorway". Con
Qwen-Image dice cosa togliere, se lo ha riconosciuto male ("the lamp post"). Con il Riempimento generativo è
obbligatorio: cosa disegnare ("a wooden bench").

## Uso

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

AI Remove si può aprire anche dal menu Start, da Applicazioni o dal menu delle app: lavora sulla foto attiva di
LightCraft o di Chromaforge se uno dei due è aperto, altrimenti su una foto che scegli tu (vedi "Da solo" in alto). Su
Mac puoi anche trascinare una foto sulla sua icona.

## Lingua

AI Remove è in **inglese** e in **italiano**. Di base segue la lingua di LightCraft, altrimenti quella di
Chromaforge. Puoi sceglierla dal pulsante in alto a destra nella finestra (`EN ▾` / `IT ▾`); vale dalla volta dopo che
apri AI Remove. Per forzarla si usa la variabile `AIREMOVE_LANG=it` oppure `AIREMOVE_LANG=en`.

## Dove finiscono i file

- `<nome>-AIRemove.dng` (da un'immagine: `.jpg`, `.png`… come l'originale): la foto ritoccata, nella cartella
  dell'originale e impilata con lui in LightCraft o in Chromaforge (da solo: solo nella cartella).
- `<nome della foto>.airemove`: il progetto, con tutte le rimozioni e le varianti, accanto alla foto. Con un doppio
  clic apre la foto in AI Remove.
- `~/AIRemove`: il programma, i modelli, i log (`install.log` e `work/last-run.log`).

## Con un assistente AI (MCP)

La cartella `mcp/` contiene un server MCP. Permette a un assistente AI (Claude, Cursor, VS Code...) di:

- controllare il computer e spiegare cosa verrà scaricato;
- installare AI Remove e configurarlo per LightCraft e/o Chromaforge;
- aprirlo o rimuovere oggetti senza finestra.

La configurazione è descritta in [mcp/README.md](mcp/README.md). Gli agenti con accesso al terminale trovano le
istruzioni in [AGENTS.md](AGENTS.md).

## Aggiornare e disinstallare

- **Aggiornare**: rilancia l'installer della nuova versione. Tiene ciò che c'è già e non riscarica i modelli.
- **Disinstallare**:
  - Windows: *Impostazioni > App > AI Remove for LightCraft and Chromaforge*;
  - Mac: `Uninstall AI Remove.command` nella cartella `AIRemove`;
  - Linux: `uninstall.sh` nella cartella `AIRemove`.

  La disinstallazione toglie il programma, i modelli e le impostazioni aggiunte a LightCraft e Chromaforge. Le foto, i
  DNG creati e i progetti `.airemove` restano.

## Problemi frequenti

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
  usano la GPU.
- **LightCraft o Chromaforge in Flatpak (Linux)**: l'installer dà all'app i permessi necessari: rete locale, cartella
  `AIRemove`, avvio di programmi esterni. Si possono togliere con
  `flatpak override --user --reset ai.storyteller.lightcraft` (LightCraft) o
  `flatpak override --user --reset com.emmertex.chromaforge` (Chromaforge).

## Privacy e sicurezza

Le foto non lasciano mai il computer. Dopo l'installazione l'unica richiesta a internet è il controllo giornaliero
di nuove versioni (vedi sopra). Per parlare con LightCraft e con Chromaforge, AI Remove usa i loro canali di controllo,
raggiungibili solo dal tuo computer (127.0.0.1):
- **quello di LightCraft** (porta 7980) è **senza password**: mentre LightCraft è aperto, qualunque programma sul tuo
  computer può comandarlo;
- **quello di Chromaforge** (porta 7981) vuole un token che l'app scrive nella sua cartella delle impostazioni: lo
  possono usare solo i programmi che leggono quella cartella.

La disinstallazione li disattiva.

## Licenze

Il codice di AI Remove è distribuito con licenza MIT ([LICENSE.txt](LICENSE.txt)). I modelli hanno le loro licenze e
vengono scaricati dalle loro fonti, non sono inclusi nel pacchetto: i dettagli sono in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
