# Endringslogg

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
