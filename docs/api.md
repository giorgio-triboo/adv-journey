# Documentazione Integrazione Web

# Service SOAP

## 1. Informazioni Generali

#### Il servizio espone metodi SOAP per l'inserimento di lead e la verifica del loro stato.

- **Endpoint WSDL:** h"ps://tmkprows2.cepu.it/Triboo2025.asmx?WSDL
- **Base URL:** h"ps://tmkprows2.cepu.it/Triboo2025.asmx
- **Protocollo:** SOAP 1.1 / 1.
- **Encoding:** UTF- 8

## 2. Autenticazione

#### Per utilizzare i metodi è necessario includere le seguenti credenziali nel body della

#### richiesta XML (campi User e Pw):

- **User:** Triboo202 5
- **Password:** 9Nb6!*HsH812*m7m*

## 3. Metodo: AddLead

#### Utilizzato per l'inserimento di una nuova anagrafica (Lead) nel sistema.

- **SOAPAction:** [http://tempuri.org/AddLead](http://tempuri.org/AddLead)
- **HTTP Method:** POST

### Esempio Struttura XML (Request)

#### XML

POST /PapiroNet2025.asmx HTTP/1.
Host: tmkprows2.cepu.it
Content-Type: text/xml; charset=utf- 8
Content-Length: length
SOAPAction: "http://tempuri.org/AddLead"

<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
xmlns:xsd="http://www.w3.org/2001/XMLSchema"
xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
<soap:Body>
<AddLead xmlns="http://tempuri.org/">
<User>***USER***</User>
<Pw>***PASSWORD***</Pw>
<Nome>string</Nome>
<Cognome>string</Cognome>
<Email>string</Email>
<Provincia>string</Provincia>
<Telefono>string</Telefono>
<UserDateTime>dateTime</UserDateTime>


<UserIp>string</UserIp>
<DataNascita>dateTime</DataNascita>
<FormId>string</FormId>
<IdMessaggio>int</IdMessaggio>
<ServizioBrand>string</ServizioBrand>
<Consenso>short</Consenso>
<UserId>string</UserId>
<Note>string</Note>
<tem:Attivita>attivita </tem:Attivita>
</AddLead>
</soap:Body>
</soap:Envelope>

### Tabella Parametri di Input

#### Parametro Tipo Obbligatorio Descrizione / Note

#### User String Sì Username fornito.

#### Pw String Sì Password fornita.

#### Nome String Sì Nome del contatto.

#### Cognome String Sì Cognome del contatto.

#### Email String Sì Indirizzo email valido.

#### Provincia String Sì Sigla della provincia (es. RM, MI).

#### Telefono String Sì Numero di telefono.

#### UserDateTime DateTime Sì

#### Data/ora compilazione form. Formato ISO 8601

#### (es. 2019 - 11 - 30T06:57:30+00:00).

#### UserIp String Sì

#### Indirizzo IP del client. Se non disponibile usare

#### 0.0.0.0.

#### DataNascita DateTime No

#### Se non disponibile inviare default: 1900 - 01 -

#### 01T11:00:00+00:00.

#### FormId String Sì Costante fornita da noi (in base al corso).

#### IdMessaggio Int Sì Variabile fornita da noi (in base al servizio).

#### ServizioBrand String Sì Costante fornita da noi.

#### Consenso Short Sì

#### Privacy: 1 (Acconsento), 0 (Non

#### acconsento/Proseguo comunque).

#### UserId String Sì

#### Vostra chiave univoca. Max 100 char. Sarà

#### usata per interrogare lo stato (metodo StatoLead).

#### Note String No Eventuali note libere.

#### Attivita String No Tutor personale (tutor-si)

### Valori di Ritorno (Response)

#### Il metodo restituisce una stringa che deve essere interpretata come segue:

#### 1. Inserimento OK:

#### o Formato: ok + UnivocoForm (codice alfanumerico interno).


#### 2. Errore:

#### o Formato: KO + NomeVariabile che ha generato l'errore.

#### 3. Duplicato:

#### o Formato: Errore - Nominativo Doppio + Var UserId + UnivocoForm.

## 4. Metodo: StatoLead

#### Utilizzato per interrogare lo stato di lavorazione di una lead precedentemente inviata,

#### utilizzando il vostro UserId come chiave di ricerca.

- **SOAPAction:** [http://tempuri.org/StatoLead](http://tempuri.org/StatoLead)
- **HTTP Method:** POST

### Esempio Struttura XML (Request)

#### XML

POST /PapiroNet2025.asmx HTTP/1.
Host: tmkprows2.cepu.it
Content-Type: text/xml; charset=utf- 8
Content-Length: length
SOAPAction: "http://tempuri.org/StatoLead"

<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
xmlns:xsd="http://www.w3.org/2001/XMLSchema"
xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
<soap:Body>
<StatoLead xmlns="http://tempuri.org/">
<User>***USER***</User>
<Pw>***PASSWORD***</Pw>
<UserId>string</UserId>
</StatoLead>
</soap:Body>
</soap:Envelope>

### Tabella Parametri di Input

#### Parametro Tipo Descrizione

#### User String Username fornito.

#### Pw String Password fornita.

#### UserId String La chiave univoca inviata da voi durante la AddLead.

### Valori di Ritorno (Response)

#### Restituisce una stringa descrittiva dello stato attuale della lead nel CRM. Esempi possibili:

- In Lavorazione NV
- NO CRM
- RIFIUTATO NV
- Rif. N.V.
- Non interessato ai nostri servizi + [Data e Ora]


- CRM + [Data e Ora]

```
Errore - Id Non Trovato
```
- In Lavorazione NV (Ancora in gestione al numero verde, deve ancora essere inserito in
CRM)
- CRM
- CRM - FISSATO
- CRM - SVOLTO
- CRM – ACCETTATO
- NO CRM SA (servizio Accoglienza)
-
- NO CRM - RIFIUTATO NV - Rif. N.V. - Cerca altro
- NO CRM - RIFIUTATO NV - Rif. N.V. - Corso nn erogabile
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio ADL
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Beauty Academy
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Callegari
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Cepu
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Cepu Crediti
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio CepuCampus
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Cepuweb
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio CTR Stipulato-Non Definito
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Formass
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Già Iscritto
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Glo
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio GS
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio InCampus
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Master
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Open
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio SRE
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Stessa Lavorazione
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Stesso Brand
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio Unich
- NO CRM - RIFIUTATO NV - Rif. N.V. - Doppio UnieCampus
- NO CRM - RIFIUTATO NV - Rif. N.V. - Esigenza risolta
- NO CRM - RIFIUTATO NV - Rif. N.V. - in lav. eCampus
- NO CRM - RIFIUTATO NV - Rif. N.V. - in lav. Studium
- NO CRM - RIFIUTATO NV - Rif. N.V. - Inconsapevole della richiesta
- NO CRM - RIFIUTATO NV - Rif. N.V. - Italiano rich Lavoro
- NO CRM - RIFIUTATO NV - Rif. N.V. - Italiano senza requisiti
- NO CRM - RIFIUTATO NV - Rif. N.V. - Minorenne
- NO CRM - RIFIUTATO NV - Rif. N.V. - Minorenne Scherzo
- NO CRM - RIFIUTATO NV - Rif. N.V. - Non interessato ai nostri servizi
- NO CRM - RIFIUTATO NV - Rif. N.V. - Non più interessato
- NO CRM - RIFIUTATO NV - Rif. N.V. - Numero inesistente
- NO CRM - RIFIUTATO NV - Rif. N.V. - Numero inesistente


- NO CRM - RIFIUTATO NV - Rif. N.V. - Numero nn corrisponde
- NO CRM - RIFIUTATO NV - Rif. N.V. - Numero straniero
- NO CRM - RIFIUTATO NV - Rif. N.V. - Recapiti errati
- NO CRM - RIFIUTATO NV - Rif. N.V. - Richiesta Lavoro
- NO CRM - RIFIUTATO NV - Rif. N.V. - Richiesta per errore
- NO CRM - RIFIUTATO NV - Rif. N.V. - Scherzo
- NO CRM - RIFIUTATO NV - Rif. N.V. - Senza Requisiti
- NO CRM - RIFIUTATO NV - Rif. N.V. - Sollecito
- NO CRM - RIFIUTATO NV - Rif. N.V. - Solo e-mail
- NO CRM - RIFIUTATO NV - Rif. N.V. - Straniero rich Lavoro
- NO CRM - RIFIUTATO NV - Rif. N.V. - Straniero senza requisiti
- NO CRM - ALTRO


