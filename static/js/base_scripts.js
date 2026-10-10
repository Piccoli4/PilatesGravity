// Navbar de vidrio: menú móvil
const navMenu = document.getElementById('navMenu');
const menuToggle = document.getElementById('menuToggle');

function setMenu(abierto) {
    navMenu.classList.toggle('show', abierto);
    menuToggle.setAttribute('aria-expanded', abierto ? 'true' : 'false');
}

menuToggle.addEventListener('click', function (e) {
    e.stopPropagation();
    setMenu(!navMenu.classList.contains('show'));
});

// Cierra el menú al elegir una opción o al tocar fuera
navMenu.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', () => setMenu(false));
});
document.addEventListener('click', function (e) {
    if (navMenu.classList.contains('show') && !navMenu.contains(e.target)) setMenu(false);
});

// Navbar más sólida al scrollear
const siteNav = document.getElementById('siteNav');
function marcarScroll() {
    siteNav.classList.toggle('is-scrolled', window.scrollY > 24);
}
window.addEventListener('scroll', marcarScroll, { passive: true });
marcarScroll();

// ── Chat de WhatsApp ──────────────────────────────────────────────
(function () {
    const chat = document.getElementById('gChat');
    const chatBox = document.getElementById('chatBox');
    const openBtn = document.getElementById('openChat');
    const closeBtn = document.getElementById('closeChat');
    const badge = document.getElementById('whatsappNotification');
    const textarea = document.getElementById('whatsappMessage');
    const sendBtn = document.getElementById('startWhatsapp');
    if (!chat || !chatBox || !openBtn) return;

    const TELEFONO = '5493425114448';
    const MENSAJE_POR_DEFECTO = '¡Hola! Quiero saber más sobre Pilates Gravity';

    function setChat(abierto) {
        chat.classList.toggle('is-open', abierto);
        chatBox.setAttribute('aria-hidden', abierto ? 'false' : 'true');
        openBtn.setAttribute('aria-expanded', abierto ? 'true' : 'false');
        if (abierto) {
            if (badge) badge.classList.remove('is-on');
            setTimeout(() => textarea && textarea.focus({ preventScroll: true }), 250);
        }
    }

    openBtn.addEventListener('click', e => { e.stopPropagation(); setChat(!chat.classList.contains('is-open')); });
    if (closeBtn) closeBtn.addEventListener('click', () => setChat(false));

    // La tarjeta de WhatsApp de la sección Contacto también abre el chat
    const desdeContacto = document.getElementById('openChatFromPhone');
    if (desdeContacto) {
        desdeContacto.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); setChat(true); });
    }

    // Respuestas rápidas
    document.querySelectorAll('[data-chat-chip]').forEach(chip => {
        chip.addEventListener('click', () => { textarea.value = chip.dataset.chatChip; textarea.focus(); });
    });

    // Enviar: abre WhatsApp una sola vez con el mensaje (o uno por defecto)
    function enviar() {
        const mensaje = (textarea.value || '').trim() || MENSAJE_POR_DEFECTO;
        window.open('https://wa.me/' + TELEFONO + '?text=' + encodeURIComponent(mensaje), '_blank', 'noopener');
        textarea.value = '';
        setChat(false);
    }
    if (sendBtn) sendBtn.addEventListener('click', enviar);
    if (textarea) {
        textarea.addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviar(); }
        });
    }

    // Cerrar al tocar fuera o con Escape
    document.addEventListener('click', e => {
        if (chat.classList.contains('is-open') && !chat.contains(e.target)) setChat(false);
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') setChat(false); });

    // Aviso de mensaje nuevo a los pocos segundos
    setTimeout(() => { if (badge && !chat.classList.contains('is-open')) badge.classList.add('is-on'); }, 4000);
})();

// Confirmación antes de cerrar sesión
document.addEventListener('DOMContentLoaded', function() {
    const logoutBtn = document.querySelector('.logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', function(e) {
            if (!confirm('¿Estás seguro de que quieres cerrar sesión?')) {
                e.preventDefault();
            }
        });
    }
});
// El registro del service worker está en templates/base.html
