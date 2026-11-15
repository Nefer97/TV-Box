# Istruzioni per Claude Code: preparare il disco del Mac mini

Leggi tutto questo file prima di fare qualsiasi cosa. Parla con l'utente in italiano.
L'utente non è sempre esperto di Linux: spiega in breve cosa fa ogni passaggio e
**non eseguire nulla che scriva su un disco senza la sua conferma esplicita**.

## Obiettivo

Su questo PC Linux è (o sarà) collegato via USB-SATA il disco interno di un **Apple Mac mini
Mid 2007 (Macmini2,1, Core 2 Duo, firmware EFI a 32 bit, GPU Intel GMA 950)**. Il contenuto
attuale del disco (un vecchio Windows) non serve: va cancellato.

Bisogna installare su quel disco, **da questo PC, senza avviare il Mac mini**:

1. **Debian 13 "trixie" amd64** minimale, che il Mac mini avvierà in **modalità BIOS/legacy (CSM)**:
   - tabella partizioni **MBR (msdos)**, una partizione ext4 con flag boot;
   - **GRUB `i386-pc`** (pacchetto `grub-pc`) nel MBR del disco;
   - niente EFI: il firmware a 32 bit del Mac mini dà problemi con il GRUB EFI di Debian 13.
2. Il progetto **tvbox** (questa cartella): Smart TV in modalità kiosk con Chrome, comandata
   dall'Apple Remote. Si installa lanciando `install.sh` **dentro il chroot** del disco.

Alla fine l'utente rimonta il disco nel Mac mini, lo accende e deve comparire la schermata TV.

## Metodo obbligato: uno script che lancia l'utente

`sudo` richiede una password che tu non puoi digitare. Quindi:

1. Scrivi uno script **`prepare-disk.sh`** in questa cartella, con tutti i passaggi qui sotto.
2. Mostralo all'utente e spiegalo in poche righe.
3. L'utente lo lancia lui in un terminale normale: `sudo ./prepare-disk.sh /dev/sdX`.
4. Se qualcosa va storto, l'utente ti incolla l'errore: correggi lo script, che deve poter
   ripartire da capo senza problemi.

## Sicurezza (non negoziabile)

- Identifica il disco **confrontando `lsblk -d -o NAME,SIZE,MODEL,TRAN,SERIAL` prima e dopo**
  che l'utente lo collega. Il disco del Mac mini è un 2,5" SATA da 80-160 GB (o un SSD, se lo
  ha sostituito) e risulta con `TRAN=usb`. Fai confermare all'utente modello e dimensione.
- Lo script deve rifiutarsi di procedere se:
  - il dispositivo non esiste o non è un disco intero (`lsblk -dno TYPE` deve dare `disk`);
  - una qualsiasi partizione o volume derivato dal disco è montato o usato come swap
    (`lsblk -nro MOUNTPOINT /dev/sdX` deve essere vuoto: così si esclude anche il disco di
    sistema, comprese configurazioni LVM o LUKS);
  - questo PC non è `x86_64` (serve per eseguire il chroot amd64).
- Prima di cancellare, lo script mostra modello e dimensione e chiede di digitare `CANCELLA`.
- Non toccare nessun altro disco o file di sistema di questo PC, salvo l'installazione dei
  pacchetti necessari (`debootstrap`, `parted`, `e2fsprogs`, `debian-archive-keyring` se
  la distribuzione non è Debian o Ubuntu). Prima chiedi all'utente.
- Usa un `trap` per smontare sempre tutto (`umount -R`) in caso di errore.

## Passaggi dello script

1. **Disco:** `wipefs -a`, poi `parted -s DISK mklabel msdos mkpart primary ext4 1MiB 100% set 1 boot on`,
   poi `partprobe` e `udevadm settle`. Ricava la partizione con
   `lsblk -nrpo NAME,TYPE DISK | awk '$2=="part"{print $1; exit}'` e formattala con
   `mkfs.ext4 -F -L tvroot`.
2. **Sistema base:** monta la partizione su `/mnt/tvbox-target` e lancia
   `debootstrap --arch=amd64 --components=main,contrib,non-free-firmware trixie /mnt/tvbox-target http://deb.debian.org/debian`.
3. **Chroot:** monta con bind `/dev`, `/dev/pts`, `/proc`, `/sys`; copia `/etc/resolv.conf` con
   `cp -L`. Crea `/usr/sbin/policy-rc.d` con `exit 101`, così i servizi non partono dentro il
   chroot; toglilo alla fine.
4. **Configurazione:**
   - `/etc/apt/sources.list`: trixie, trixie-updates e trixie-security, componenti
     `main contrib non-free-firmware`;
   - `/etc/fstab`: la radice per `UUID=`, ext4, `errors=remount-ro 0 1`;
   - hostname `tv` e riga `127.0.1.1 tv` in `/etc/hosts`;
   - fuso `Europe/Rome`;
   - locale `it_IT.UTF-8` (installa `locales`, abilita la riga in `/etc/locale.gen`,
     poi `locale-gen` e `update-locale LANG=it_IT.UTF-8`);
   - tastiera italiana: `/etc/default/keyboard` con `XKBLAYOUT="it"` scritto **prima** di
     installare `console-setup`.
5. **Pacchetti** (`DEBIAN_FRONTEND=noninteractive`): `linux-image-amd64 grub-pc locales
   console-setup openssh-server avahi-daemon libnss-mdns sudo systemd-timesyncd`. Imposta prima
   via debconf `grub-pc/install_devices_empty boolean true`, così il pacchetto non si ferma.
6. **Rete via cavo, indipendente dall'hardware:** crea `/etc/systemd/network/20-wired.network`
   con `[Match] Name=en* eth*` e `[Network] DHCP=yes`, poi `systemctl enable systemd-networkd`.
   **Alla fine** di tutto installa `systemd-resolved`: rimpiazza `resolv.conf` e, se lo installi
   prima, rompe i DNS nel chroot.
7. **Utente amministratore** `admin`, nei gruppi `sudo`. La password la sceglie l'utente:
   lo script la chiede con `passwd admin` dentro il chroot, in modo interattivo, e non va mai
   salvata in un file. Root resta bloccato. Serve per entrare via SSH: `ssh admin@tv.local`.
8. **tvbox:** copia questa cartella in `/root/tvbox` del disco ed esegui
   `chroot /mnt/tvbox-target bash /root/tvbox/install.sh`. Lo script è già adatto al chroot:
   gli errori di `modprobe`, `udevadm` e `systemctl daemon-reload` sono tollerati.
   Installa Google Chrome dal repository di Google, crea l'utente `tv` con autologin e
   configura GRUB in modalità silenziosa.
9. **GRUB:** `grub-install --target=i386-pc DISK` dal chroot, poi `update-grub`. Controlla
   che `/boot/grub/grub.cfg` usi `root=UUID=...`.
10. **Servizio del primo avvio** `tvbox-firstboot.service` (oneshot,
    `ConditionPathExists=!/var/lib/tvbox-firstboot.done`), che parte **solo se**
    `/sys/class/dmi/id/product_name` inizia con `Macmini` (usa `ExecCondition`). Deve:
    - trovare il disco della radice (`findmnt -no SOURCE /`, poi `lsblk -no PKNAME`) e il suo
      link `/dev/disk/by-id/ata-*`;
    - impostare `grub-pc/install_devices` su quel link con `debconf-set-selections`;
    - eseguire `grub-install` e `update-grub`, poi creare il file `.done`.

    Senza questo servizio i futuri aggiornamenti di `grub-pc` cercherebbero il disco con il
    nome che ha adesso su questo PC (USB).
11. **Pulizia:** `apt-get clean`, rimuovi `policy-rc.d`, `sync`, smonta tutto.
12. **Verifiche finali**, da stampare a schermo:
    - kernel e initrd presenti in `/boot`;
    - `grub.cfg` presente;
    - `google-chrome-stable` installato;
    - `/opt/tvbox/tvd.py` e `/etc/tvbox/config.json` presenti;
    - utenti `tv` e `admin` creati;
    - `getty@tty1` con autologin;
    - servizi `ssh`, `systemd-networkd` e `mac-power-restore` abilitati.

## Prova facoltativa prima di rimontare il disco

Se c'è QEMU (`qemu-system-x86_64`), proponi all'utente di avviare il disco in una macchina
virtuale BIOS, per verificare che GRUB e il kernel partano:

```
sudo qemu-system-x86_64 -m 2048 -drive file=/dev/sdX,format=raw -enable-kvm -nic user,model=e1000
```

Il servizio del primo avvio e quello della corrente non partono in QEMU, perché non è un Mac
mini. Chrome in QEMU potrebbe non comportarsi come sul Mac mini: conta solo che il sistema si avvii.

## Cosa dire all'utente alla fine

1. Spegnere tutto, staccare il disco e rimontarlo nel Mac mini.
2. Collegare TV (DVI→HDMI), audio (jack o ottico), **cavo di rete** e accendere.
3. Se non parte da solo, riaccendere tenendo premuto **Option/Alt** (con una tastiera USB) e
   scegliere il disco (può comparire come "Windows").
4. Seguire la guida "Smart TV Linux su Mac mini 2007" dal punto 9.3: login su RaiPlay e
   Mediaset, audio, collaudo.
5. Per assistenza: `ssh admin@tv.local`; il log di tvbox è `/home/tv/.tvbox.log`.

## Contesto del progetto, in breve

- `tvd.py`: demone Python che avvia e sorveglia Chrome in kiosk, serve il launcher su
  `127.0.0.1:8765` e legge l'Apple Remote (driver `hid-appleir`, tramite evdev e uinput).
  Comanda Chrome con il DevTools Protocol sulla porta 9222, solo in locale.
- La configurazione è in `/etc/tvbox/config.json`, la risoluzione in `/etc/tvbox/session.env`
  (1280x720).
- Non modificare `tvd.py`, il launcher o la configurazione: sono già stati provati. Se pensi
  che serva una modifica, chiedi prima all'utente.
