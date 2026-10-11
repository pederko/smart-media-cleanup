# Endringslogg

## 0.7.1
- Beskyttelse (som Barn-biblioteket og «keep»-tagger) hindrer ikke lenger opprydding i duplikater og ekstra versjoner – én fil blir alltid igjen. Kan slås på igjen under Innstillinger → Beskyttelse. Beskyttelsen mot å slette hele titler gjelder som før.

## 0.7.0
- Ny duplikatside: oppsummering øverst, faner per type med antall, søk, filter for kopier i nedlastingsmappen og sortering etter gevinst.
- Velg hvilken fil som beholdes med ett klikk per gruppe, kryss av grupper og slett overflødige filer etter en oppsummering.
- Sletting av duplikatfiler er av som standard og krever både en bryter i Innstillinger og at mappene er montert uten `:ro`. Filer Radarr/Sonarr kjenner slettes aldri slik, filen som beholdes blir alltid liggende, og hver fil kontrolleres (uendret siden skanning, inne i biblioteket, ikke symlenke) rett før sletting.

## 0.6.1
- Slett-knapp direkte i tittelvisningen: «Slett filmen», «Slett hele serien» og «Slett sesong N», med gevinsten på knappen.
- Avkrysning og «Slett valgte…» vises alltid i Forslag, Filmer, Serier og på brukersidene. Er sletting av, forklarer dialogen hvor den slås på.
- «Skrivebeskyttet / Sletting er på» nederst i menyen lenker til Innstillinger.

## 0.6.0
- Nye sider **Filmer** og **Serier**: oppsummering øverst (hvor mye som brukes, hva som aldri er sett eller ikke sett på lenge, trygge slettinger, 4K), forslag fordelt på type, «Bør ses på først» med plakater, og en filtrer- og sorterbar liste med anbefaling per tittel.
- Ny side **Brukere** med alle som har bedt om noe i Seerr, og en egen side per bruker: hva de har bedt om, hva de har sett selv, hva ingen har sett, og hvor mye som frigjøres ved å fjerne det de ikke har sett. Filtre for «Ikke sett av brukeren», «over 12 måneder» og «Ikke sett av noen».
- Velg titler direkte fra disse sidene og slett dem (når sletting er slått på).
- Mindre støy i loggen: API-kall logges ikke lenger enkeltvis.

## 0.5.0
- Sletting via Radarr og Sonarr (av som standard, slås på under Innstillinger → Sletting): hele filmer, hele serier og enkeltsesonger (avovervåkes før filene slettes).
- Oppsummering før sletting med plass som frigjøres og hva som ikke tas med, og hvorfor. Én bekreftelsesknapp.
- Serveren avviser beskyttede titler, kontrollerer at utvalget ikke er endret siden oppsummeringen, og sjekker mappen i Radarr/Sonarr rett før hver sletting.
- Ny side «Logg» med alle slettinger. Full oppdatering startes automatisk etterpå.

## 0.4.0
- Plakater for filmer og serier, de samme som i Plex, i forslag, titler, oversikten og tittelvisningen. Radarr/Sonarr brukes som reserve.
- Bildene hentes av appen (Plex-token forlater aldri serveren) og lagres i `data/posters` i 30 dager.

## 0.3.0
- Appen sier fra når en ny versjon er ute: banner øverst og lenke nederst i menyen, med lenke til hva som er nytt. Sjekker GitHub-releases hver 6. time og kan slås av under Innstillinger → Oppdateringer.
- YAML-filen bruker nå `:latest`, så TrueNAS viser «Update available» og oppdaterer med Update-knappen – uten å endre taggen.

## 0.2.2
- Rettet: skanning av store biblioteker feilet med «database is locked». Fremdrift skrives nå i minnet i stedet for til databasen mens jobben holder en skrivetransaksjon.
- Skanneren slipper skrivelåsen minst hvert annet sekund og under pauser, så API og planlegger ikke blokkeres.
- Ny test med 3000 filer, ekte fremdriftsrapportering og samtidige skrivere.

## 0.2.1
- Appikon (også som ikon i nettleserfanen) og skript som setter ikonet i TrueNAS Apps.
- «Web UI»-knapp i TrueNAS via `x-portals` i YAML-filen.
- Skjermbilder i README og tydeligere installasjonsinstruks.

## 0.2.0
- Seerr: viser hvem som ba om hver film/serie i forslag, titler og tittelvisning.
- Filter «Etterspurt av» i forslag og titler, og oversikt per bruker (antall titler, plass, hvor mye de ikke har sett selv).
- Forespørsler kobles via TMDB/TVDB (Radarr/Sonarr) og Plex ratingKey (titler utenfor Radarr/Sonarr, f.eks. Barn).
- Ny poenglinje: +8 når de som ba om en tittel for over 12 måneder siden aldri har sett den. −15 hvis etterspurt siste 12 måneder (som før).
- Avspillinger matches mot både Tautulli-visningsnavn og Plex-brukernavn.
- Image bygges og publiseres til GitHub Container Registry med GitHub Actions.

## 0.1.0
- Første skrivebeskyttede versjon: skanning, kobling mot Radarr/Sonarr/Plex/Tautulli, forslag med forklarbar prioritet, duplikater, gevinst uten dobbelttelling.
