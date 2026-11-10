# Pomodoro

Widget de escritorio, siempre visible, con un temporizador de trabajo y descanso.

La ventana no tiene barra de título. Se arrastra desde cualquier zona libre del cuerpo y queda por encima del resto de las aplicaciones.

## Controles

- **Start** / **Stop**: inicia o pausa el temporizador.
- **Reset**: vuelve al comienzo del tiempo de trabajo.
- **Engrane**: abre el menú para definir los minutos de trabajo (1 a 120) y de descanso (1 a 60). También incluye **Salir**.

Al iniciar un periodo de trabajo suena un beep. Al terminarlo suenan tres beeps cortos y empieza el descanso. Al terminar el descanso suena un beep y vuelve a empezar el trabajo. Pausar y reanudar no vuelve a emitir el beep de inicio.

Los valores iniciales son 25 minutos de trabajo y 5 de descanso. Esos minutos y la posición de la ventana se recuerdan al cerrar.

## Ejecutar desde el código

Hace falta Python 3.10 o superior.

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

## Ejecutable

```bat
build.bat
```

El script crea el entorno virtual si no existe, instala las dependencias y deja el programa en `dist\Pomodoro.exe`.
