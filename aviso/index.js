/* Aviso de Cloudflare: cada hora pide a GitHub que ejecute la tarea «Generar
   el tiempo», igual que pulsar «Run workflow» en la pestaña Actions.

   Por qué: las tareas programadas de GitHub se lanzan con horas de retraso o
   no se lanzan (del 21 al 24 de noviembre de 2026, 9 de unas 40). Las que se
   piden así arrancan al momento. La programación de GitHub sigue puesta como
   respaldo. Si no hay pasada nueva de ECMWF, la tarea acaba en un minuto.

   Necesita el secreto GITHUB_TOKEN en este Worker (Cloudflare → Workers →
   tiempo-aviso → Configuración → Variables y secretos): un token de GitHub de
   grano fino, solo para el repositorio tiempo, con el permiso «Actions: Read
   and write». No tiene dirección pública: solo corre con el reloj. */
const TAREA = 'https://api.github.com/repos/javierjimenezcuadros/tiempo/actions/workflows/generar.yml/dispatches';

export default {
  async scheduled(evento, env) {
    if (!env.GITHUB_TOKEN) throw new Error('Falta el secreto GITHUB_TOKEN');
    const r = await fetch(TAREA, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN.trim()}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'tiempo-aviso',
      },
      body: JSON.stringify({ ref: 'main' }),
    });
    if (!r.ok) throw new Error(`GitHub respondió ${r.status}: ${(await r.text()).slice(0, 300)}`);
    console.log('Tarea pedida a GitHub');
  },
};
