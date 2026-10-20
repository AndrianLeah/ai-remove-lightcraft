<p align="center">
  <img src="assets/icon/airemove-256.png" width="128" alt="Icona di AI Remove: un procione inciso">
</p>

<h1 align="center">AI Remove per LightCraft</h1>

[English](README.md)

Toglie oggetti e persone dalle foto RAW con l'intelligenza artificiale, direttamente dentro LightCraft. Fa quello che
in Lightroom è "Rimozione generativa", ma tutto gira sul tuo computer.

1. In LightCraft scegli una foto RAW e premi **Ctrl+Shift+X** (**Cmd+Shift+X** su Mac).
2. Nella finestra di AI Remove clicca su ciò che vuoi togliere: SAM 3 lo seleziona tutto.
3. Premi **Rimuovi selezione**: vengono generate alcune varianti e tu scegli la migliore. Per togliere anche l'ombra
   o il riflesso dell'oggetto, premi prima **Includi l'ombra**: li aggiunge alla selezione, in blu.
   Pali, cavi e cordoni lunghi vengono riempiti a tasselli lungo l'oggetto, ognuno vicino alla misura del modello:
   il riempimento resta nitido invece di essere un'immagine piccola ingrandita. Per quelli sottili si aggiunge una
   variante LaMa, che continua meglio ciò che c'è dietro. **Dettaglio pieno** ridisegna la variante scelta alla
   risoluzione della foto.
4. Premi **Salva in LightCraft**: il risultato è un **DNG RAW** (`<nome>-AIRemove.dng`), impilato sopra l'originale e
   con lo stesso sviluppo. Puoi continuare a svilupparlo come un RAW qualsiasi.

Ogni rimozione resta modificabile: la puoi rigenerare, cambiare variante o eliminare in qualsiasi momento. Tutto è
salvato in un unico file accanto al RAW (`<raw>.airemove`). Il RAW originale non viene mai modificato.

> AI Remove è un plug-in **non ufficiale**: non è fatto, sponsorizzato né approvato dal team di ArtCraft, che sviluppa
> LightCraft.

## Cosa serve

| | |
|---|---|
| **LightCraft** | installato (getartcraft.com) |
| **Windows 10/11** | scheda NVIDIA, AMD Radeon RX 7000/9000 o Intel Arc; senza GPU funziona solo LaMa |
| **macOS 12+** | Mac con chip Apple (M1 o successivi); meglio con almeno 16 GB di memoria |
| **Linux x86-64** | scheda NVIDIA, oppure AMD con ROCm |
| **Spazio su disco** | da 5 GB (solo LaMa) a circa 30 GB (tutti i modelli) |
| **Internet** | solo durante l'installazione |

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
2. ti chiede quali modelli installare, mostrando il peso e la licenza di ciascuno;
3. scarica Python e PyTorch nella cartella `AIRemove` della tua home;
4. crea il programma "AI Remove" con la sua icona (menu Start, Applicazioni o menu delle app);
5. configura LightCraft: attiva il suo canale di controllo, imposta AI Remove come editor esterno e assegna la
   scorciatoia.

Ci vogliono da 10 minuti a un'ora, quasi tutto per i download.

**Dopo l'installazione riavvia LightCraft una volta**: legge l'impostazione del canale di controllo solo all'avvio.

Se LightCraft era aperto, l'installer ti chiede di chiuderlo per scrivere le impostazioni. Puoi anche ripetere solo
questo passaggio più tardi, con `installer/bootstrap.ps1 --configure-lightcraft` su Windows o
`installer/bootstrap.sh --configure-lightcraft` su Mac e Linux.

### SAM 3 e FLUX: token di Hugging Face

- **SAM 3** è lo stesso modello delle maschere *Oggetto* di LightCraft. Se LightCraft l'ha già scaricato, AI Remove
  usa quella copia e non scarica niente.
- **FLUX**, e SAM 3 se LightCraft non ce l'ha, hanno una licenza da accettare su Hugging Face:
  1. crea un account gratuito su [huggingface.co](https://huggingface.co);
  2. accetta la licenza sulla pagina del modello:
     [facebook/sam3](https://huggingface.co/facebook/sam3),
     [black-forest-labs/FLUX.1-Fill-dev](https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev);
  3. crea un token di tipo *Read* su [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) e
     incollalo quando l'installer lo chiede.

Senza SAM 3 la selezione si fa col pennello, oppure con una maschera chiamata "Rimuovi" (o "Remove") fatta in LightCraft.

## I modelli

| Modello | Quando usarlo | Peso | Licenza |
|---|---|---|---|
| **LaMa** | Oggetti piccoli e medi su sfondi semplici (muro, cielo, prato, asfalto). Gira sul processore, un solo risultato in pochi secondi. | 0,2 GB | Apache-2.0 |
| **SDXL** | Aree medie con dettagli: inventa contenuto coerente con la scena e ogni variante è diversa. Circa 8–15 s a variante con una GPU. | 6,9 GB | CreativeML Open RAIL++-M |
| **FLUX Fill + Turbo** | Il più realistico: rispetta luce, prospettiva e architettura. Per aree grandi o difficili. Serve una GPU da 12 GB o più. | 16,6 GB | FLUX.1 [dev] Non-Commercial |
| **SAM 3** | La selezione con un clic. | 3,4 GB, oppure 0 GB se è già in LightCraft | SAM License (Meta) |
| **OSOR** (facoltativo, su FLUX) | Toglie l'oggetto insieme alla sua ombra e al riflesso, in un solo passo (3–8 s). È lui che trova l'ombra per "Includi l'ombra". | 0,6 GB | FLUX.1 [dev] Non-Commercial |
| **ObjectClear** (facoltativo) | Toglie l'oggetto insieme alla sua ombra e al riflesso, circa 5 s a variante, a 512 px. | 7,3 GB | S-Lab License 1.0 (non commerciale) |

Il testo facoltativo **in inglese** guida il riempimento, per esempio "old plaster wall" o "dark doorway".

## Uso

| | Windows / Linux | Mac |
|---|---|---|
| Seleziona un oggetto | clic | clic |
| Togli una parte / aggiungi una parte | Alt+clic / Shift+clic | Option+clic / Shift+clic |
| Pennello / Gomma / Clic SAM | B / E / S | B / E / S |
| Dimensione del pennello | `[` `]` oppure Alt+rotella | `[` `]` oppure Option+rotella |
| Elimina un oggetto dalla selezione | clic destro | clic destro (o Ctrl+clic) |
| Zoom | Ctrl+rotella, `+` `−`, `0` = adatta | Cmd+rotella, `+` `−`, `0` = adatta |
| Sposta la vista | rotella, tasto centrale, Spazio+trascina | due dita, Spazio+trascina |
| Annulla | Ctrl+Z | Cmd+Z |
| Confronta con l'originale | tieni premuto "Originale" o `\` | tieni premuto "Originale" o `\` |
| Rimuovi selezione | Invio | Invio |

AI Remove si può aprire anche dal menu Start, da Applicazioni o dal menu delle app: lavora sempre sulla foto attiva in
LightCraft.

## Lingua

AI Remove è in **inglese** e in **italiano**. Di base segue la lingua di LightCraft. Puoi sceglierla dal pulsante in
alto a destra nella finestra (`EN ▾` / `IT ▾`); vale dalla volta dopo che apri AI Remove. Per forzarla si usa la
variabile `AIREMOVE_LANG=it` oppure `AIREMOVE_LANG=en`.

## Dove finiscono i file

- `<nome>-AIRemove.dng`: la foto ritoccata, nella cartella dell'originale e impilata con lui in LightCraft.
- `<nome del raw>.airemove`: il progetto, con tutte le rimozioni e le varianti, accanto al RAW.
- `~/AIRemove`: il programma, i modelli, i log (`install.log` e `work/last-run.log`).

## Con un assistente AI (MCP)

La cartella `mcp/` contiene un server MCP. Permette a un assistente AI (Claude, Cursor, VS Code...) di:

- controllare il computer e spiegare cosa verrà scaricato;
- installare e configurare AI Remove;
- aprirlo o rimuovere oggetti senza finestra.

La configurazione è descritta in [mcp/README.md](mcp/README.md). Gli agenti con accesso al terminale trovano le
istruzioni in [AGENTS.md](AGENTS.md).

## Aggiornare e disinstallare

- **Aggiornare**: rilancia l'installer della nuova versione. Tiene ciò che c'è già e non riscarica i modelli.
- **Disinstallare**:
  - Windows: *Impostazioni > App > AI Remove for LightCraft*;
  - Mac: `Uninstall AI Remove.command` nella cartella `AIRemove`;
  - Linux: `uninstall.sh` nella cartella `AIRemove`.

  La disinstallazione toglie il programma, i modelli e le impostazioni aggiunte a LightCraft. Le foto, i DNG creati e i
  progetti `.airemove` restano.

## Problemi frequenti

- **"LightCraft non risponde"**: LightCraft è chiuso oppure è stato aperto prima dell'installazione. Riavvialo. Su
  Linux con Wayland la sua finestra deve essere visibile.
- **La prima variante è lenta (AMD)**: la GPU compila i suoi programmi la prima volta che incontra una dimensione,
  poi va veloce.
- **Mac: "Python vorrebbe accedere a…"**: se i RAW sono su un disco esterno, sulla Scrivania o in Documenti, macOS
  chiede una volta il permesso. Rispondi *Consenti*.
- **Memoria della GPU esaurita**: usa SDXL invece di FLUX, oppure meno varianti, e chiudi gli altri programmi che
  usano la GPU.
- **LightCraft Flatpak (Linux)**: l'installer gli dà i permessi necessari: rete locale, cartella `AIRemove`, avvio di
  programmi esterni. Si possono togliere con `flatpak override --user --reset ai.storyteller.lightcraft`.

## Privacy e sicurezza

Le foto non lasciano mai il computer. Per parlare con LightCraft, AI Remove usa il suo canale di controllo:
un'interfaccia raggiungibile solo dal tuo computer (127.0.0.1, porta 7980), ma **senza password**. Mentre LightCraft è
aperto, qualunque programma sul tuo computer può comandarlo. La disinstallazione lo disattiva.

## Licenze

Il codice di AI Remove è distribuito con licenza MIT ([LICENSE.txt](LICENSE.txt)). I modelli hanno le loro licenze e
vengono scaricati dalle loro fonti, non sono inclusi nel pacchetto: i dettagli sono in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
