Questo il flusso che possiamo fare API:
1) Interrogare Ulixe che mi risponde lo stato della lead in quel momento (vedi documentazione per approfondire)
2) Le chiamate possono esser fatte  nella notte dalle 22 alle 06 di mattina. Inserire dilay appropriato magari ogni 0,5s per chiamata
3) Per query molto grosse, al massimo indietro di 1 mese. altrimenti siamo liberi di andare indietro e seguire tutte le lead.
4) Per gestire al meglio dovremmo creare un mini-tool con DB per monitorare lo stato (es. fare le chiamate per tutte le lead del giorno corrente + fare le chiamate alle lead che non hanno uno stato definitivo in modo da seguire avanzamento lavori)
5) I rifiutati non rientra in circolo quindi possiamo scartarli dalle chiamate
6) Tutto ciò che è "in lavorazione può tornare in circolo" quindi bisogna fare follow dello stato
7) con questo metodo possiamo sia avere lo stato delle lavorazioni/vedite per singola LEAD che rimandare i dati a Meta



l'idea è fare un applicativo con:
front-end tabella
script che richiede i dati da magellano (capire se endpoint o script autonomo con plyground)
script che richiede i dati ad ulixe
salvataggio in database dei valori di ulixe
update delle anagrafiche magellano (da capire se fare o no)
pulizia delle lead con stato "non lavorabile" dopo 30 giorni dalla
