let slideIndex = 0;
showSlides();

function showSlides() {
    let slides = document.getElementsByClassName("slide");
    let dots = document.getElementsByClassName("dot");
    for (let i = 0; i < slides.length; i++) {
        slides[i].style.display = "none";
    }
    slideIndex++;
    if (slideIndex > slides.length) {
        slideIndex = 1;
    }
    for (let i = 0; i < dots.length; i++) {
        dots[i].className = dots[i].className.replace(" active", "");
    }
    slides[slideIndex - 1].style.display = "block";
    dots[slideIndex - 1].className += " active";
}

function currentSlide(n) {
    slideIndex = n - 1; // Adjust to match showSlides' increment logic
    showSlides();
}

function decreaseSlide() {
    console.log("decreae")
    let slide = slideIndex - 1;
    if (slide < 1) slide = document.getElementsByClassName("slide").length;
    currentSlide(slide);
}

function increaseSlide() {
    console.log("increase")
    let slide = slideIndex + 1;
    if (slide > document.getElementsByClassName("slide").length) slide = 1;
    currentSlide(slide);
}
