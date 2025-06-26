// Muestra el menu
document.getElementById('menuToggle').addEventListener('click', function () {
    document.querySelector('nav ul').classList.toggle('show');
});

// Cierra el menú al hacer clic en cualquier ítem del nav en pantallas menores a 768px
document.querySelectorAll('nav ul li a').forEach(link => {
    link.addEventListener('click', () => {
        if (window.innerWidth <= 768) {
            document.querySelector('nav ul').classList.remove('show');
        }
    });
});

// Muestra el chat al hacer clic en el botón de WhatsApp o en la card de teléfono en la section de contacto
function openChatBox() {
    document.getElementById('chatBox').style.display = 'block';
    document.getElementById('openChat').style.display = 'none';

    // Oculta la notificación si existe
    const notif = document.getElementById('whatsappNotification');
    if (notif) notif.style.display = 'none';

    // Opcional: enfocar el textarea
    document.getElementById('whatsappMessage').focus();
}

document.getElementById('openChat').addEventListener('click', openChatBox);

// Verificar si existe el elemento antes de agregar el event listener
const openChatFromPhone = document.getElementById('openChatFromPhone');
if (openChatFromPhone) {
    openChatFromPhone.addEventListener('click', function (e) {
        e.preventDefault();
        openChatBox();
    });
}

// Muestra una notificación tras 3 segundos
setTimeout(() => {
    const notif = document.getElementById('whatsappNotification');
    if (notif) {
        notif.style.display = 'flex';
    }
}, 3000);

// Función para cerrar el chat
function closeChatBox() {
    document.getElementById('chatBox').style.display = 'none';
    document.getElementById('openChat').style.display = 'flex';
}

// Cierra el chat al hacer clic en el botón de cerrar
document.getElementById('closeChat').addEventListener('click', function () {
    closeChatBox();
});

// Cierra el chat al hacer clic fuera de él
document.addEventListener('click', function (e) {
    const chatBox = document.getElementById('chatBox');
    const openChatButton = document.getElementById('openChat');
    const openChatPhone = document.getElementById('openChatFromPhone');

    if (
        chatBox.style.display === 'block' &&
        !chatBox.contains(e.target) &&
        !openChatButton.contains(e.target) &&
        (!openChatPhone || !openChatPhone.contains(e.target))
    ) {
        closeChatBox();
    }
});

// Envía el mensaje de WhatsApp al hacer clic en "Iniciar chat"
document.getElementById('startWhatsapp').addEventListener('click', function (e) {
    const message = document.getElementById('whatsappMessage').value.trim();
    if (message !== '') {
        const phoneNumber = '5493425114448';
        const whatsappURL = `https://wa.me/${phoneNumber}?text=${encodeURIComponent(message)}`;
        window.open(whatsappURL, '_blank');

            // Cierra el chat y limpia el mensaje
        document.getElementById('chatBox').style.display = 'none';
        document.getElementById('openChat').style.display = 'flex';
        document.getElementById('whatsappMessage').value = '';
    } else {
        alert('Por favor escribí un mensaje antes de enviar.');
    }
});

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