#!/usr/bin/env python3
"""Generate the bundled demo vault: a small science & astronomy knowledge base.

    python tools/make_demo_vault.py [out_dir]     (default: demo-vault/)

Deterministic: the same script always writes the same vault. Notes link the way a
real vault does — maps of content (MOCs) as hubs, topics clustered by field with
cross-links, people linked to their work, observing logs and reading notes as
leaves, and an Archive of superseded theories pointing at what replaced them.
"""

from __future__ import annotations

import os
import random
import shutil
import sys

# field -> (folder, MOC title, tag, [(title, one-line description, [explicit links])])
FIELDS = {
    "Astronomy": ("Astronomy", "Astronomy MOC", "astronomy", [
        ("Sun", "The G-type main-sequence star at the centre of the Solar System, about 4.6 billion years old.", ["Nuclear Fusion", "Solar Wind", "Main Sequence"]),
        ("Solar Wind", "A stream of charged particles flowing outward from the Sun's corona.", ["Magnetosphere", "Aurora"]),
        ("Aurora", "Light emitted when solar-wind particles excite atoms in the upper atmosphere.", ["Magnetosphere"]),
        ("Mercury", "The smallest planet and the closest to the Sun, with no substantial atmosphere.", ["Perihelion Precession of Mercury"]),
        ("Venus", "A rocky planet with a runaway greenhouse atmosphere of carbon dioxide.", ["Greenhouse Effect"]),
        ("Earth", "The third planet from the Sun and the only one known to host life.", ["Plate Tectonics", "Moon"]),
        ("Moon", "Earth's only natural satellite, probably formed after a giant impact.", ["Tides", "Giant Impact Hypothesis"]),
        ("Mars", "A cold desert planet with the largest volcano in the Solar System, Olympus Mons.", ["Olympus Mons", "Perseverance Rover"]),
        ("Olympus Mons", "A shield volcano on Mars roughly 22 km high.", []),
        ("Jupiter", "The largest planet, a gas giant with a storm larger than Earth.", ["Great Red Spot", "Galilean Moons"]),
        ("Great Red Spot", "A persistent anticyclonic storm in Jupiter's atmosphere observed for centuries.", []),
        ("Galilean Moons", "Io, Europa, Ganymede and Callisto, discovered by Galileo in 1610.", ["Europa", "Galileo Galilei"]),
        ("Europa", "An icy moon of Jupiter thought to hide a global subsurface ocean.", ["Astrobiology"]),
        ("Saturn", "A gas giant famous for its bright ring system.", ["Rings of Saturn", "Titan"]),
        ("Rings of Saturn", "A ring system made mostly of water-ice particles.", ["Cassini–Huygens"]),
        ("Titan", "Saturn's largest moon, with a thick nitrogen atmosphere and methane lakes.", ["Cassini–Huygens"]),
        ("Uranus", "An ice giant whose rotation axis is tilted almost onto its orbital plane.", ["William Herschel"]),
        ("Neptune", "An ice giant predicted mathematically before it was observed in 1846.", ["Urbain Le Verrier"]),
        ("Pluto", "A dwarf planet in the Kuiper Belt, visited by New Horizons in 2015.", ["Kuiper Belt", "New Horizons"]),
        ("Kuiper Belt", "A disk of icy bodies beyond Neptune's orbit.", ["Comets"]),
        ("Oort Cloud", "A hypothesised spherical shell of icy bodies far beyond the Kuiper Belt.", ["Comets"]),
        ("Comets", "Icy bodies that grow comae and tails when they approach the Sun.", ["Halley's Comet"]),
        ("Halley's Comet", "A periodic comet returning about every 76 years.", ["Edmond Halley"]),
        ("Asteroid Belt", "A region between Mars and Jupiter populated by rocky bodies.", ["Ceres"]),
        ("Ceres", "The largest object in the Asteroid Belt, classed as a dwarf planet.", []),
        ("Exoplanets", "Planets orbiting stars other than the Sun.", ["Transit Method", "Habitable Zone"]),
        ("Transit Method", "Detecting exoplanets by the dimming of a star as a planet passes in front.", ["Kepler Space Telescope"]),
        ("Habitable Zone", "The range of orbits where liquid water could exist on a planet's surface.", ["Astrobiology"]),
        ("Main Sequence", "The band on the H–R diagram where stars fuse hydrogen in their cores.", ["Hertzsprung–Russell Diagram"]),
        ("Hertzsprung–Russell Diagram", "A plot of stellar luminosity against temperature.", ["Stellar Evolution"]),
        ("Stellar Evolution", "How stars change over their lifetimes, from birth to remnant.", ["Red Giant", "White Dwarf", "Supernova"]),
        ("Red Giant", "A late stage of a low- or intermediate-mass star after core hydrogen runs out.", ["Planetary Nebula"]),
        ("Planetary Nebula", "A glowing shell of gas ejected by a dying red giant.", ["White Dwarf"]),
        ("White Dwarf", "The dense, Earth-sized remnant core of a low-mass star.", ["Chandrasekhar Limit"]),
        ("Chandrasekhar Limit", "The maximum mass (about 1.4 solar masses) of a stable white dwarf.", ["Subrahmanyan Chandrasekhar"]),
        ("Supernova", "The explosive death of a massive star or a white dwarf.", ["Neutron Stars", "Nucleosynthesis"]),
        ("Neutron Stars", "Ultra-dense stellar remnants made largely of neutrons.", ["Pulsars"]),
        ("Pulsars", "Rotating neutron stars that sweep beams of radiation like lighthouses.", ["Jocelyn Bell Burnell"]),
        ("Black Holes", "Regions of spacetime where gravity prevents anything, even light, from escaping.", ["Event Horizon", "Accretion Disk", "General Relativity"]),
        ("Event Horizon", "The boundary around a black hole beyond which escape is impossible.", ["Hawking Radiation"]),
        ("Accretion Disk", "A rotating disk of matter spiralling into a massive object and heating as it falls.", ["Quasars"]),
        ("Quasars", "Extremely luminous galactic nuclei powered by accreting supermassive black holes.", ["Active Galactic Nuclei"]),
        ("Active Galactic Nuclei", "Compact galactic centres emitting far more energy than their stars can account for.", []),
        ("Sagittarius A*", "The supermassive black hole at the centre of the Milky Way.", ["Event Horizon Telescope"]),
        ("Milky Way", "Our home galaxy, a barred spiral containing hundreds of billions of stars.", ["Sagittarius A*", "Spiral Galaxies"]),
        ("Andromeda Galaxy", "The nearest large spiral galaxy, on course to merge with the Milky Way.", ["Spiral Galaxies"]),
        ("Spiral Galaxies", "Disk galaxies with arms of young stars winding out from a central bulge.", ["Density Wave Theory"]),
        ("Density Wave Theory", "Explains spiral arms as long-lived compression waves moving through a galactic disk.", []),
        ("Elliptical Galaxies", "Smooth, featureless galaxies dominated by older stars.", []),
        ("Nebulae", "Clouds of gas and dust where stars form or that stars leave behind.", ["Orion Nebula", "Star Formation"]),
        ("Orion Nebula", "A nearby stellar nursery visible to the naked eye in Orion's sword.", ["Star Formation"]),
        ("Star Formation", "The collapse of cold molecular clouds into new stars.", ["Protoplanetary Disk"]),
        ("Protoplanetary Disk", "A disk of gas and dust around a young star from which planets form.", []),
        ("Gravitational Waves", "Ripples in spacetime produced by accelerating masses.", ["LIGO", "General Relativity"]),
        ("Gravitational Lensing", "The bending of light around massive objects.", ["General Relativity", "Dark Matter"]),
        ("Astrobiology", "The study of life's origins, evolution and distribution in the universe.", ["Abiogenesis", "Drake Equation"]),
        ("Drake Equation", "A framework for estimating the number of communicating civilisations in the galaxy.", ["Fermi Paradox"]),
        ("Fermi Paradox", "The apparent contradiction between the likelihood of alien life and the lack of evidence for it.", []),
        ("Parallax", "Measuring distance from a star's apparent shift as Earth orbits the Sun.", ["Cosmic Distance Ladder"]),
        ("Cosmic Distance Ladder", "The chain of methods used to measure ever-greater astronomical distances.", ["Cepheid Variables"]),
        ("Cepheid Variables", "Pulsating stars whose period reveals their luminosity, making them standard candles.", ["Henrietta Swan Leavitt"]),
    ]),
    "Cosmology": ("Cosmology", "Cosmology MOC", "cosmology", [
        ("Big Bang", "The model in which the universe expanded from an extremely hot, dense early state.", ["Cosmic Microwave Background", "Hubble's Law"]),
        ("Cosmic Microwave Background", "Relic radiation from about 380,000 years after the Big Bang.", ["Penzias and Wilson"]),
        ("Hubble's Law", "Galaxies recede at speeds proportional to their distance.", ["Edwin Hubble", "Redshift"]),
        ("Redshift", "The stretching of light to longer wavelengths as sources recede or space expands.", ["Doppler Effect"]),
        ("Cosmic Inflation", "A proposed burst of exponential expansion in the first fraction of a second.", []),
        ("Dark Matter", "Unseen mass inferred from its gravitational effects on galaxies and light.", ["Galaxy Rotation Curves", "Vera Rubin"]),
        ("Galaxy Rotation Curves", "Outer stars orbit too fast for visible mass alone, implying dark matter.", ["Vera Rubin"]),
        ("Dark Energy", "The unknown cause of the accelerating expansion of the universe.", ["Cosmological Constant"]),
        ("Cosmological Constant", "A term in Einstein's equations acting as the energy density of empty space.", ["Albert Einstein"]),
        ("Big Bang Nucleosynthesis", "Formation of the lightest nuclei in the first minutes after the Big Bang.", ["Nucleosynthesis"]),
        ("Large-Scale Structure", "The cosmic web of filaments, clusters and voids.", ["Dark Matter"]),
        ("Observable Universe", "The region from which light has had time to reach us since the Big Bang.", []),
        ("Lambda-CDM Model", "The standard model of cosmology: dark energy plus cold dark matter.", ["Dark Energy", "Dark Matter"]),
        ("Heat Death of the Universe", "A possible end state in which the universe reaches maximum entropy.", ["Entropy"]),
        ("Multiverse", "Speculative proposals that our universe is one of many.", []),
        ("Hubble Tension", "Disagreement between measurements of the universe's current expansion rate.", ["Hubble's Law"]),
    ]),
    "Physics": ("Physics", "Physics MOC", "physics", [
        ("Newton's Laws of Motion", "Three laws relating force, mass and motion.", ["Isaac Newton", "Classical Mechanics"]),
        ("Classical Mechanics", "The physics of macroscopic bodies moving at everyday speeds.", []),
        ("Universal Gravitation", "Newton's law that every mass attracts every other mass.", ["Isaac Newton"]),
        ("Kepler's Laws", "Three laws describing planetary orbits as ellipses.", ["Johannes Kepler"]),
        ("Special Relativity", "Physics at high speeds: the speed of light is the same for all observers.", ["Albert Einstein", "Mass–Energy Equivalence"]),
        ("Mass–Energy Equivalence", "E = mc²: mass and energy are interchangeable.", ["Nuclear Fusion"]),
        ("General Relativity", "Gravity as the curvature of spacetime by mass and energy.", ["Albert Einstein", "Perihelion Precession of Mercury"]),
        ("Perihelion Precession of Mercury", "An orbital anomaly explained exactly by general relativity.", []),
        ("Spacetime", "The four-dimensional fabric combining space and time.", []),
        ("Time Dilation", "Moving clocks, and clocks deep in gravity, tick more slowly.", ["GPS"]),
        ("GPS", "Satellite navigation that must correct for relativistic time dilation.", []),
        ("Electromagnetism", "The unified theory of electric and magnetic fields.", ["Maxwell's Equations"]),
        ("Maxwell's Equations", "Four equations describing electric and magnetic fields and light.", ["James Clerk Maxwell"]),
        ("Electromagnetic Spectrum", "The range of light from radio waves to gamma rays.", ["Spectroscopy"]),
        ("Thermodynamics", "The physics of heat, work and energy.", ["Entropy"]),
        ("Entropy", "A measure of disorder that never decreases in an isolated system.", ["Ludwig Boltzmann"]),
        ("Statistical Mechanics", "Explains thermodynamics from the behaviour of vast numbers of particles.", ["Ludwig Boltzmann"]),
        ("Quantum Mechanics", "The physics of the very small, where energy comes in discrete quanta.", ["Wave–Particle Duality", "Uncertainty Principle"]),
        ("Wave–Particle Duality", "Light and matter behave as both waves and particles.", ["Double-Slit Experiment"]),
        ("Double-Slit Experiment", "Single particles produce an interference pattern, revealing wave behaviour.", []),
        ("Uncertainty Principle", "Position and momentum cannot both be known exactly.", ["Werner Heisenberg"]),
        ("Schrödinger Equation", "The equation governing how quantum states evolve.", ["Erwin Schrödinger"]),
        ("Quantum Entanglement", "Correlations between particles that persist across any distance.", ["Bell's Theorem"]),
        ("Bell's Theorem", "Shows no local hidden-variable theory can reproduce quantum predictions.", []),
        ("Photoelectric Effect", "Light ejects electrons only above a threshold frequency, evidence for photons.", ["Albert Einstein"]),
        ("Standard Model", "The theory of the known elementary particles and three of the four forces.", ["Higgs Boson", "Quarks"]),
        ("Higgs Boson", "The particle linked to the field that gives other particles mass, found in 2012.", ["Large Hadron Collider"]),
        ("Quarks", "Fundamental particles that combine to form protons and neutrons.", []),
        ("Neutrinos", "Nearly massless particles that rarely interact with matter.", []),
        ("Antimatter", "Matter made of antiparticles with opposite charge.", ["Paul Dirac"]),
        ("Nuclear Fusion", "Light nuclei combining into heavier ones, releasing energy; it powers the stars.", ["Sun"]),
        ("Nuclear Fission", "Heavy nuclei splitting into lighter ones, releasing energy.", ["Lise Meitner"]),
        ("Radioactivity", "The spontaneous decay of unstable atomic nuclei.", ["Marie Curie"]),
        ("Hawking Radiation", "Theoretical thermal radiation emitted by black holes.", ["Stephen Hawking"]),
        ("Doppler Effect", "A change in observed frequency due to relative motion.", []),
        ("Spectroscopy", "Studying matter by how it absorbs and emits light.", ["Spectral Lines"]),
        ("Spectral Lines", "Dark or bright lines that fingerprint the elements in a light source.", []),
        ("String Theory", "A candidate theory of everything in which particles are vibrating strings.", []),
        ("Quantum Field Theory", "The framework combining quantum mechanics with special relativity.", ["Richard Feynman"]),
        ("Superconductivity", "Zero electrical resistance in some materials at low temperature.", []),
        ("Tides", "The rise and fall of sea levels caused by the Moon's and Sun's gravity.", []),
        ("Magnetosphere", "The region around a planet dominated by its magnetic field.", []),
    ]),
    "Chemistry": ("Chemistry", "Chemistry MOC", "chemistry", [
        ("Periodic Table", "Elements arranged by atomic number, revealing repeating chemical properties.", ["Dmitri Mendeleev"]),
        ("Atomic Structure", "Atoms as a dense nucleus surrounded by electrons.", ["Rutherford Gold Foil Experiment", "Bohr Model"]),
        ("Rutherford Gold Foil Experiment", "Showed that an atom's positive charge sits in a tiny nucleus.", ["Ernest Rutherford"]),
        ("Bohr Model", "Electrons occupy discrete energy levels around the nucleus.", ["Niels Bohr"]),
        ("Chemical Bonds", "Forces holding atoms together in molecules and solids.", ["Covalent Bond", "Ionic Bond"]),
        ("Covalent Bond", "Atoms sharing pairs of electrons.", []),
        ("Ionic Bond", "Attraction between oppositely charged ions.", []),
        ("Oxidation", "The loss of electrons in a chemical reaction.", ["Antoine Lavoisier"]),
        ("Combustion", "Rapid oxidation that releases heat and light.", ["Oxidation"]),
        ("Catalysis", "Speeding up reactions without consuming the catalyst.", ["Enzymes"]),
        ("Organic Chemistry", "The chemistry of carbon compounds.", []),
        ("Water", "A polar molecule whose hydrogen bonds make life's chemistry possible.", []),
        ("Nucleosynthesis", "The creation of new atomic nuclei in stars and explosions.", ["Supernova"]),
        ("Isotopes", "Atoms of one element with different numbers of neutrons.", ["Radiometric Dating"]),
        ("Radiometric Dating", "Dating materials using the steady decay of radioactive isotopes.", ["Radioactivity"]),
        ("Acids and Bases", "Substances that donate or accept protons.", []),
        ("Polymers", "Long chains of repeating molecular units.", []),
        ("Electrolysis", "Driving a chemical reaction with an electric current.", ["Michael Faraday"]),
    ]),
    "Biology": ("Biology", "Biology MOC", "biology", [
        ("Evolution by Natural Selection", "Heritable traits that aid survival become more common over generations.", ["Charles Darwin", "Alfred Russel Wallace"]),
        ("Cell Theory", "All living things are made of cells, which come from other cells.", []),
        ("DNA", "The double-helix molecule that stores genetic information.", ["Rosalind Franklin", "Double Helix"]),
        ("Double Helix", "The twisted-ladder structure of DNA described in 1953.", ["Rosalind Franklin"]),
        ("Genetics", "The study of heredity and variation.", ["Gregor Mendel"]),
        ("Mendelian Inheritance", "Traits passed on as discrete units, from Mendel's pea experiments.", ["Gregor Mendel"]),
        ("Central Dogma", "Information flows from DNA to RNA to protein.", ["DNA", "Proteins"]),
        ("Proteins", "Chains of amino acids that fold into the machinery of life.", ["Enzymes"]),
        ("Enzymes", "Proteins that catalyse biochemical reactions.", []),
        ("Photosynthesis", "Converting light, water and carbon dioxide into sugar and oxygen.", ["Chloroplasts"]),
        ("Chloroplasts", "Organelles where photosynthesis takes place.", ["Endosymbiotic Theory"]),
        ("Mitochondria", "Organelles that produce most of a cell's chemical energy.", ["Endosymbiotic Theory"]),
        ("Endosymbiotic Theory", "Mitochondria and chloroplasts descend from free-living bacteria.", ["Lynn Margulis"]),
        ("Abiogenesis", "The origin of life from non-living chemistry.", ["Miller–Urey Experiment"]),
        ("Miller–Urey Experiment", "Produced amino acids from simple gases and electric sparks.", []),
        ("Tree of Life", "The branching evolutionary relationships among all organisms.", []),
        ("Extremophiles", "Organisms that thrive in extreme heat, cold, acidity or pressure.", ["Astrobiology"]),
        ("Ecosystems", "Communities of organisms interacting with their environment.", []),
        ("Germ Theory", "Many diseases are caused by microorganisms.", ["Louis Pasteur"]),
        ("Vaccination", "Training the immune system with harmless forms of a pathogen.", ["Edward Jenner"]),
        ("Antibiotics", "Drugs that kill or inhibit bacteria.", ["Alexander Fleming"]),
        ("CRISPR", "A gene-editing tool adapted from a bacterial immune system.", ["DNA"]),
        ("Human Genome Project", "The international effort that sequenced the human genome by 2003.", ["DNA"]),
        ("Neurons", "Cells that transmit information as electrical and chemical signals.", []),
        ("Cambrian Explosion", "A rapid diversification of animal life around 538 million years ago.", ["Fossils"]),
        ("Fossils", "Preserved remains or traces of ancient organisms.", ["Mary Anning"]),
    ]),
    "Earth Science": ("Earth Science", "Earth Science MOC", "earth-science", [
        ("Plate Tectonics", "Earth's lithosphere is broken into moving plates.", ["Continental Drift"]),
        ("Earthquakes", "Sudden ground shaking as stress releases along faults.", ["Plate Tectonics"]),
        ("Volcanoes", "Openings where molten rock reaches the surface.", ["Plate Tectonics"]),
        ("Rock Cycle", "How igneous, sedimentary and metamorphic rocks transform into one another.", []),
        ("Greenhouse Effect", "Atmospheric gases trapping heat radiated from a planet's surface.", ["Climate Change"]),
        ("Climate Change", "Long-term shifts in temperature and weather, now driven largely by human emissions.", []),
        ("Ice Ages", "Long periods of reduced global temperature and expanded ice sheets.", ["Milankovitch Cycles"]),
        ("Milankovitch Cycles", "Periodic changes in Earth's orbit that pace the ice ages.", []),
        ("Ozone Layer", "Stratospheric ozone that absorbs most of the Sun's ultraviolet light.", []),
        ("Giant Impact Hypothesis", "The Moon formed from debris after a Mars-sized body struck early Earth.", []),
        ("Age of the Earth", "About 4.54 billion years, measured by radiometric dating.", ["Radiometric Dating"]),
        ("Deep Time", "The immense span of geological time.", ["James Hutton"]),
    ]),
    "Mathematics": ("Mathematics", "Mathematics MOC", "mathematics", [
        ("Calculus", "The mathematics of change and accumulation.", ["Isaac Newton", "Gottfried Leibniz"]),
        ("Differential Equations", "Equations relating functions to their rates of change.", ["Calculus"]),
        ("Non-Euclidean Geometry", "Geometries where parallel lines can meet or diverge.", ["General Relativity"]),
        ("Probability Theory", "The mathematics of chance and uncertainty.", []),
        ("Statistics", "Collecting and interpreting data to draw conclusions.", ["Probability Theory"]),
        ("Chaos Theory", "Deterministic systems that are extremely sensitive to initial conditions.", []),
        ("Fourier Analysis", "Breaking signals into sums of sine waves.", ["Spectroscopy"]),
        ("Linear Algebra", "Vectors, matrices and linear transformations.", ["Quantum Mechanics"]),
        ("Group Theory", "The mathematics of symmetry.", ["Standard Model"]),
        ("Information Theory", "Quantifying information, founded by Claude Shannon.", ["Entropy"]),
        ("Prime Numbers", "Integers greater than one divisible only by one and themselves.", []),
        ("Infinity", "Concepts of the unbounded, including different sizes of infinite sets.", []),
    ]),
    "Instruments & Missions": ("Instruments & Missions", "Instruments & Missions MOC", "missions", [
        ("Hubble Space Telescope", "An orbiting optical telescope launched in 1990.", ["Edwin Hubble"]),
        ("James Webb Space Telescope", "An infrared observatory launched in 2021 to see the early universe.", ["Exoplanets"]),
        ("Kepler Space Telescope", "Found thousands of exoplanets with the transit method.", ["Transit Method"]),
        ("Event Horizon Telescope", "A planet-sized array that imaged a black hole's shadow in 2019.", ["Black Holes"]),
        ("LIGO", "Laser interferometers that first detected gravitational waves in 2015.", ["Gravitational Waves"]),
        ("Large Hadron Collider", "The world's largest particle accelerator, at CERN.", ["Higgs Boson"]),
        ("Voyager Program", "Two probes launched in 1977, now in interstellar space.", ["Jupiter", "Saturn"]),
        ("New Horizons", "The probe that flew past Pluto in 2015.", ["Pluto"]),
        ("Cassini–Huygens", "Studied Saturn for 13 years and landed a probe on Titan.", ["Saturn", "Titan"]),
        ("Apollo Program", "NASA's crewed Moon landings, 1969–1972.", ["Moon"]),
        ("Perseverance Rover", "A Mars rover searching for signs of ancient life in Jezero Crater.", ["Mars"]),
        ("Gaia", "A space observatory mapping the positions and motions of over a billion stars.", ["Parallax"]),
        ("Refracting Telescope", "A telescope that gathers light with lenses.", ["Galileo Galilei"]),
        ("Reflecting Telescope", "A telescope that gathers light with mirrors, pioneered by Newton.", ["Isaac Newton"]),
        ("Radio Telescopes", "Dishes and arrays that observe the sky at radio wavelengths.", ["Pulsars"]),
        ("Penzias and Wilson", "The radio astronomers who discovered the cosmic microwave background in 1965.", []),
    ]),
    "People": ("People", "People MOC", "people", [
        ("Galileo Galilei", "Pointed a telescope at the sky and found Jupiter's moons and the phases of Venus.", ["Heliocentrism"]),
        ("Nicolaus Copernicus", "Placed the Sun, not Earth, at the centre of the planetary system.", ["Heliocentrism"]),
        ("Johannes Kepler", "Discovered that planets move in ellipses.", ["Kepler's Laws", "Tycho Brahe"]),
        ("Tycho Brahe", "Made the most precise naked-eye astronomical observations of his era.", []),
        ("Isaac Newton", "Formulated the laws of motion and universal gravitation.", ["Newton's Laws of Motion", "Universal Gravitation", "Calculus"]),
        ("Gottfried Leibniz", "Developed calculus independently of Newton.", ["Calculus"]),
        ("Edmond Halley", "Predicted the return of the comet that bears his name.", ["Halley's Comet"]),
        ("William Herschel", "Discovered Uranus and infrared radiation.", ["Uranus", "Caroline Herschel"]),
        ("Caroline Herschel", "Discovered several comets and catalogued nebulae.", ["Comets", "William Herschel"]),
        ("Urbain Le Verrier", "Predicted Neptune's position from irregularities in Uranus's orbit.", ["Neptune"]),
        ("Michael Faraday", "Discovered electromagnetic induction.", ["Electromagnetism", "Electrolysis"]),
        ("James Clerk Maxwell", "Unified electricity, magnetism and light.", ["Maxwell's Equations"]),
        ("Ludwig Boltzmann", "Explained entropy statistically.", ["Entropy", "Statistical Mechanics"]),
        ("Marie Curie", "Pioneered research on radioactivity and won Nobel Prizes in two sciences.", ["Radioactivity"]),
        ("Ernest Rutherford", "Discovered the atomic nucleus.", ["Rutherford Gold Foil Experiment"]),
        ("Niels Bohr", "Proposed quantised electron orbits.", ["Bohr Model", "Quantum Mechanics"]),
        ("Albert Einstein", "Developed special and general relativity and explained the photoelectric effect.", ["Special Relativity", "General Relativity", "Photoelectric Effect"]),
        ("Max Planck", "Introduced the quantum of energy in 1900.", ["Quantum Mechanics"]),
        ("Werner Heisenberg", "Formulated matrix mechanics and the uncertainty principle.", ["Uncertainty Principle"]),
        ("Erwin Schrödinger", "Wrote the wave equation of quantum mechanics.", ["Schrödinger Equation"]),
        ("Paul Dirac", "Predicted antimatter from a relativistic equation for the electron.", ["Antimatter"]),
        ("Richard Feynman", "Developed quantum electrodynamics and Feynman diagrams.", ["Quantum Field Theory"]),
        ("Lise Meitner", "Co-discovered nuclear fission.", ["Nuclear Fission"]),
        ("Emmy Noether", "Proved that symmetries correspond to conservation laws.", ["Group Theory"]),
        ("Edwin Hubble", "Showed other galaxies exist and that the universe is expanding.", ["Hubble's Law"]),
        ("Henrietta Swan Leavitt", "Found the period–luminosity relation of Cepheid variables.", ["Cepheid Variables"]),
        ("Cecilia Payne-Gaposchkin", "Showed that stars are made mostly of hydrogen and helium.", ["Spectroscopy", "Sun"]),
        ("Subrahmanyan Chandrasekhar", "Calculated the maximum mass of white dwarfs.", ["Chandrasekhar Limit"]),
        ("Vera Rubin", "Measured galaxy rotation curves that revealed dark matter.", ["Galaxy Rotation Curves", "Dark Matter"]),
        ("Jocelyn Bell Burnell", "Discovered the first pulsars in 1967.", ["Pulsars"]),
        ("Stephen Hawking", "Showed black holes should emit radiation.", ["Hawking Radiation", "Black Holes"]),
        ("Carl Sagan", "Astronomer and communicator who popularised science.", ["Pale Blue Dot", "Cosmos"]),
        ("Charles Darwin", "Proposed evolution by natural selection.", ["Evolution by Natural Selection"]),
        ("Alfred Russel Wallace", "Independently conceived natural selection.", ["Evolution by Natural Selection"]),
        ("Gregor Mendel", "Discovered the rules of heredity with pea plants.", ["Mendelian Inheritance"]),
        ("Rosalind Franklin", "Her X-ray images revealed DNA's helical structure.", ["DNA"]),
        ("Lynn Margulis", "Championed the endosymbiotic origin of organelles.", ["Endosymbiotic Theory"]),
        ("Louis Pasteur", "Established germ theory and developed early vaccines.", ["Germ Theory", "Vaccination"]),
        ("Edward Jenner", "Pioneered smallpox vaccination.", ["Vaccination"]),
        ("Alexander Fleming", "Discovered penicillin in 1928.", ["Antibiotics"]),
        ("Mary Anning", "Fossil hunter whose finds reshaped understanding of prehistoric life.", ["Fossils"]),
        ("James Hutton", "Founder of modern geology and the idea of deep time.", ["Deep Time"]),
        ("Antoine Lavoisier", "Identified oxygen's role in combustion.", ["Oxidation", "Combustion"]),
        ("Dmitri Mendeleev", "Arranged the periodic table and predicted missing elements.", ["Periodic Table"]),
        ("Ada Lovelace", "Wrote what is often considered the first computer program.", []),
        ("Claude Shannon", "Founded information theory.", ["Information Theory"]),
    ]),
    "History of Science": ("History of Science", "History of Science MOC", "history", [
        ("Heliocentrism", "The model with the Sun at the centre of the Solar System.", ["Nicolaus Copernicus", "Galileo Galilei"]),
        ("Scientific Revolution", "The 16th–17th century transformation of natural philosophy.", ["Isaac Newton", "Galileo Galilei"]),
        ("Scientific Method", "Observation, hypothesis, prediction and test.", []),
        ("Falsifiability", "Karl Popper's criterion that scientific claims must be testable.", ["Scientific Method"]),
        ("Paradigm Shift", "Thomas Kuhn's term for a fundamental change in scientific framework.", []),
        ("Royal Society", "The scientific academy founded in London in 1660.", []),
        ("Chemical Revolution", "Lavoisier's overthrow of phlogiston chemistry.", ["Antoine Lavoisier"]),
        ("Quantum Revolution", "The early 20th-century emergence of quantum theory.", ["Max Planck", "Niels Bohr"]),
        ("Space Race", "Cold War competition in spaceflight, 1957–1975.", ["Apollo Program"]),
        ("Manhattan Project", "The wartime programme that built the first nuclear weapons.", ["Nuclear Fission"]),
        ("Continental Drift", "Alfred Wegener's 1912 proposal that continents move.", ["Plate Tectonics"]),
        ("Pale Blue Dot", "The 1990 Voyager 1 photograph of Earth from 6 billion km away.", ["Voyager Program", "Carl Sagan"]),
    ]),
}

# superseded ideas, each pointing at what replaced it
ARCHIVE = [
    ("Luminiferous Aether", "A medium once thought to carry light waves; ruled out by Michelson–Morley.", ["Special Relativity"]),
    ("Phlogiston Theory", "Held that burning releases a substance called phlogiston.", ["Oxidation", "Chemical Revolution"]),
    ("Caloric Theory", "Treated heat as an invisible fluid.", ["Thermodynamics"]),
    ("Geocentric Model", "Placed a stationary Earth at the centre of the universe.", ["Heliocentrism"]),
    ("Ptolemaic Epicycles", "Circles on circles used to save geocentric planetary motions.", ["Kepler's Laws"]),
    ("Steady State Theory", "An unchanging, eternal universe with continuous creation of matter.", ["Big Bang", "Cosmic Microwave Background"]),
    ("Static Universe", "The early-20th-century assumption that the universe neither expands nor contracts.", ["Hubble's Law", "Cosmological Constant"]),
    ("Spontaneous Generation", "The idea that life routinely arises from non-living matter.", ["Germ Theory", "Louis Pasteur"]),
    ("Vulcan (Hypothetical Planet)", "A planet inside Mercury's orbit invoked to explain its precession.", ["Perihelion Precession of Mercury"]),
    ("Martian Canals", "Supposed artificial channels on Mars, later shown to be an optical illusion.", ["Mars"]),
    ("Plum Pudding Model", "Electrons embedded in a diffuse sphere of positive charge.", ["Rutherford Gold Foil Experiment"]),
    ("N-Rays", "A radiation reported in 1903 that turned out not to exist.", ["Scientific Method"]),
    ("Lamarckian Inheritance", "Inheritance of characteristics acquired during an organism's life.", ["Evolution by Natural Selection"]),
    ("Four Humours", "Ancient medicine's theory of disease as imbalance of four bodily fluids.", ["Germ Theory"]),
]

BOOKS = [
    ("Cosmos", "Carl Sagan", ["Carl Sagan", "Milky Way", "Drake Equation", "Heliocentrism"]),
    ("A Brief History of Time", "Stephen Hawking", ["Stephen Hawking", "Black Holes", "Big Bang", "Hawking Radiation"]),
    ("Pale Blue Dot (book)", "Carl Sagan", ["Pale Blue Dot", "Voyager Program", "Astrobiology"]),
    ("The First Three Minutes", "Steven Weinberg", ["Big Bang", "Big Bang Nucleosynthesis", "Cosmic Microwave Background"]),
    ("Black Holes and Time Warps", "Kip Thorne", ["Black Holes", "Gravitational Waves", "Subrahmanyan Chandrasekhar"]),
    ("Six Easy Pieces", "Richard Feynman", ["Richard Feynman", "Quantum Mechanics", "Newton's Laws of Motion"]),
    ("The Elegant Universe", "Brian Greene", ["String Theory", "General Relativity", "Quantum Mechanics"]),
    ("The Fabric of the Cosmos", "Brian Greene", ["Spacetime", "Entropy", "Cosmic Inflation"]),
    ("On the Origin of Species", "Charles Darwin", ["Charles Darwin", "Evolution by Natural Selection", "Tree of Life"]),
    ("The Selfish Gene", "Richard Dawkins", ["Genetics", "Evolution by Natural Selection", "DNA"]),
    ("The Double Helix (book)", "James Watson", ["Double Helix", "Rosalind Franklin", "DNA"]),
    ("The Structure of Scientific Revolutions", "Thomas Kuhn", ["Paradigm Shift", "Scientific Revolution"]),
    ("Seven Brief Lessons on Physics", "Carlo Rovelli", ["General Relativity", "Quantum Mechanics", "Entropy"]),
    ("Astrophysics for People in a Hurry", "Neil deGrasse Tyson", ["Dark Matter", "Dark Energy", "Big Bang"]),
    ("Silent Spring", "Rachel Carson", ["Ecosystems", "Climate Change"]),
    ("The Gene", "Siddhartha Mukherjee", ["Genetics", "Gregor Mendel", "CRISPR"]),
    ("Longitude", "Dava Sobel", ["Scientific Revolution", "Royal Society"]),
    ("The Glass Universe", "Dava Sobel", ["Henrietta Swan Leavitt", "Cecilia Payne-Gaposchkin", "Spectroscopy"]),
]

OBSERVING_TARGETS = ["Moon", "Jupiter", "Saturn", "Mars", "Venus", "Orion Nebula", "Andromeda Galaxy",
                     "Milky Way", "Galilean Moons", "Rings of Saturn", "Great Red Spot", "Comets",
                     "Planetary Nebula", "Nebulae", "Aurora", "Sun"]
EQUIPMENT = ["Refracting Telescope", "Reflecting Telescope"]
SKY = ["Clear and steady.", "Thin high cloud; seeing average.", "Excellent transparency after rain.",
       "Moonlit sky washed out faint targets.", "Gusty wind, lots of shimmer.", "Hazy near the horizon."]


def note(title, tag, desc, links, moc=None, extra=""):
    body = [f"---\ntags: [{tag}]\n---", f"# {title}", "", desc, ""]
    if extra:
        body += [extra, ""]
    if links:
        body += ["## Related", *[f"- [[{l}]]" for l in links], ""]
    if moc:
        body += [f"Part of [[{moc}]].", ""]
    return "\n".join(body)


def main(out: str) -> None:
    rnd = random.Random(42)
    if os.path.isdir(out):
        shutil.rmtree(out)
    files: dict[str, str] = {}
    all_titles = {t for _, (_, _, _, items) in FIELDS.items() for t, _, _ in items}
    all_titles |= {t for t, _, _ in ARCHIVE}

    homes = []
    for field, (folder, moc, tag, items) in FIELDS.items():
        titles = [t for t, _, _ in items]
        for title, desc, explicit in items:
            # a couple of in-field neighbours on top of the curated links, so each
            # field forms a cluster the way a real vault does
            pool = [t for t in titles if t != title and t not in explicit]
            links = list(dict.fromkeys(explicit + rnd.sample(pool, k=min(len(pool), rnd.randint(1, 3)))))
            links = [l for l in links if l in all_titles or l in {b for b, _, _ in BOOKS}]
            files[f"{folder}/{title}.md"] = note(title, tag, desc, links, moc)
        files[f"{folder}/{moc}.md"] = note(
            moc, "moc", f"Map of content for {field.lower()}.", sorted(titles), "Home")
        homes.append(moc)

    for title, desc, links in ARCHIVE:
        files[f"Archive/{title}.md"] = note(
            title, "superseded", desc, links, "Archive MOC", "*Superseded — kept for the history of the idea.*")
    files["Archive/Archive MOC.md"] = note(
        "Archive MOC", "moc", "Ideas science has moved past.", [t for t, _, _ in ARCHIVE], "Home")
    homes.append("Archive MOC")

    for book, author, links in BOOKS:
        files[f"Reading/{book}.md"] = note(
            book, "reading", f"Reading notes on *{book}* by {author}.", links, "Reading List")
    files["Reading/Reading List.md"] = note(
        "Reading List", "moc", "Books read and noted.", [b for b, _, _ in BOOKS], "Home")
    homes.append("Reading List")

    # observing journal: many small leaf notes, like daily notes in a real vault
    day = 0
    logs = []
    for _ in range(140):
        day += rnd.randint(1, 6)
        y, rem = 2024 + day // 365, day % 365
        m, d = 1 + rem // 31 % 12, 1 + rem % 28
        title = f"Observing Log {y}-{m:02d}-{d:02d}"
        if title in (t for t, _ in logs):
            continue
        targets = rnd.sample(OBSERVING_TARGETS, k=rnd.randint(1, 3))
        links = targets + [rnd.choice(EQUIPMENT)]
        logs.append((title, links))
        files[f"Journal/{title}.md"] = note(
            title, "journal", rnd.choice(SKY), links, "Observing Journal",
            "Observed: " + ", ".join(f"[[{t}]]" for t in targets) + ".")
    files["Journal/Observing Journal.md"] = note(
        "Observing Journal", "moc", "Nights at the eyepiece.", [t for t, _ in logs[-12:]], "Home")
    homes.append("Observing Journal")

    files["Home.md"] = note("Home", "moc", "Start here: a small vault about how we came to understand the universe.",
                            homes, None)
    # a few unlinked inbox notes: the galaxy leaves orphans out
    for t in ("Inbox — untitled", "Inbox — idea for a talk", "Scratch"):
        files[f"Inbox/{t}.md"] = f"# {t}\n\nNothing linked here yet.\n"

    for rel, text in files.items():
        path = os.path.join(out, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(f"wrote {len(files)} notes to {out}")


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", "demo-vault"))
