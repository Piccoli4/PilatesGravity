// Script para el modal de horarios
const openModal = document.getElementById('open-schedule-modal');
const modal = document.getElementById('schedule-modal');
const closeModal = modal.querySelector('.close-modal');

openModal.addEventListener('click', function (e) {
    e.preventDefault();
    modal.style.display = 'block';
});

closeModal.addEventListener('click', function () {
    modal.style.display = 'none';
});

window.addEventListener('click', function (e) {
    if (e.target === modal) {
        modal.style.display = 'none';
    }
});