SO-ARM101开源6轴机械臂使用文档
1. LeRobot简介
LeRobot是一个开源的机器人学习框架，由Hugging Face开发，专门用于机器人行为克隆和强化学习。该框架为研究人员和开发者提供了一个统一的平台，用于训练、部署和评估机器人策略。

1.1 核心特性
多模态数据支持：支持视觉、触觉、音频等多种传感器数据
灵活的策略架构：支持行为克隆、强化学习等多种学习范式
丰富的机器人支持：兼容多种机器人平台和硬件配置
云端训练支持：支持分布式训练和云端部署
易于扩展：模块化设计，便于添加新的机器人类型和算法
1.2 技术架构
LeRobot基于PyTorch构建，采用现代深度学习技术栈：

数据处理：高效的数据加载和预处理管道
模型训练：支持多种神经网络架构和训练策略
实时推理：优化的推理引擎，支持实时机器人控制
可视化工具：丰富的数据可视化和训练监控工具
1.3 应用场景
工业自动化：装配、分拣、焊接等工业任务

服务机器人：家庭服务、医疗辅助、教育机器人

研究开发：机器人学习算法研究和原型验证

教育培训：机器人学习和人工智能教学

1.4 生态系统
LeRobot与Hugging Face生态系统深度集成：

模型共享：通过Hugging Face Hub分享训练好的模型
数据集管理：统一的数据集存储和版本控制
社区支持：活跃的开源社区和丰富的文档资源
持续更新：定期发布新功能和性能优化
1.5 发展前景
SO-ARM101开源6轴机械臂代表了机器人学习领域的重要发展方向，通过降低机器人学习的门槛，加速了机器人技术的普及和应用。随着人工智能技术的不断发展，SO-ARM101开源6轴机械臂将继续推动机器人学习技术的创新和进步。

2. 硬件与环境准备
2.1 硬件清单

2.2 环境配置
2.2.1 安装Miniconda
(1) Windows系统安装

①下载Miniconda包

Miniconda官网安装包

找到Miniconda3-py311_25.7.0-2-Windows-x86_64.exe将包下载到电脑上。（或者直接使用：软件工具&源码程序\软件工具）


NOTE

因为官网是国外网站，这里推荐使用国内清华大学的镜像源，对于国内的网络友好，下载速度更快！

Index of /anaconda/miniconda/ | 清华大学开源软件镜像站 | Tsinghua Open Source Mirror

点击上面链接进行下载，这里选择的同样也是Miniconda3-py311_25.7.0-2-Windows-x86_64.exe。


②安装Miniconda

找到你所下载的Miniconda安装包，双击进行安装。


下方一定要全部勾选，否则环境配置会出现问题！


③换源

anaconda | 镜像站使用帮助 | 清华大学开源软件镜像站 | Tsinghua Open Source Mirror

点击链接，进入Miniconda软件仓库，找到下图所框选的第三方源。



channels:
  - defaults
show_channel_urls: true
default_channels:
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/msys2
custom_channels:
  conda-forge: https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud
  pytorch: https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud
win+R打开控制面板，输入cmd，打开终端。


终端输入指令，生成.condarc。


conda config --set show_channel_urls yes

.condarc文件一般放在用户文件下，例如C:\Users\Admin，打开.condarc，将内容进行替换，如下所示：


运行指令，清理索引缓存。


conda clean -i

(2) Ubuntu系统安装

①下载Miniconda包

Ctrl+Alt+T打开终端，输入指令，下载Miniconda包。


wget https://repo.anaconda.com/miniconda/Miniconda3-py311_25.7.0-2-Linux-x86_64.sh

②安装Miniconda

输入指令，安装Miniconda。


sh Miniconda3-py311_25.7.0-2-Linux-x86_64.sh

点击Enter继续。


输入yes，点击Enter继续。


这里默认安装到/home/ubuntu/miniconda3，如果不需要更改安装目录直接点击Enter继续即可，需要更改安装目录则输入需要安装的目录，再点击Enter。


输入yes，点击Enter就安装完成。


现在把终端关掉，重新打开终端就会出现下图界面。


如果不想默认使用的是Miniconda的python环境，需要在.bashrc文件中添加一行指令。

输入指令，打开.bashrc文件。


gedit .bashrc

找到conda initialize的代码，在下面添加一行指令，添加完Ctrl+s保存即可叉掉，重新打开终端即可。


conda config --set auto_activate false

③换源

anaconda | 镜像站使用帮助 | 清华大学开源软件镜像站 | Tsinghua Open Source Mirror

点击链接，进入Miniconda软件仓库，找到下图所框选的第三方源。



channels:
  - defaults
show_channel_urls: true
default_channels:
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/msys2
custom_channels:
  conda-forge: https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud
  pytorch: https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud
终端输入指令，生成.condarc。


conda config --set show_channel_urls yes

.condarc文件一般放在用户文件下，例如/home/ubuntu，使用gedit工具打开.condarc，输入指令，将内容进行替换，如下所示。


gedit .condarc

运行指令，清除索引缓存，输入y，点击Enter即可。


conda clean -i

2.2.2 配置虚拟环境
(1) Windows配置虚拟环境

①打开终端

win+R打开控制面板，输入cmd，打开终端。


②创建虚拟环境

输入指令，按下Enter，创建虚拟环境并安装ffmpeg包（建议7.1.1，支持 libsvtav1编码）。


conda create -n lerobot python=3.20.18 ffmpeg=7.1.1 -c conda-forge

出现下图标志，按y，再按Enter继续。


创建完成之后，输入指令，即可查到所创建的虚拟环境。


conda env list

③进入虚拟环境


conda activate lerobot

④下载代码库

SO-ARM101开源6轴机械臂工程包路径：软件工具&源码程序\源码程序\lerobot.zip

打开SO-ARM101开源6轴机械臂工程包，将工程文件，解压到桌面。


⑤安装依赖包

进入到lerobot目录，安装lerobot的依赖包并且指定添加飞特舵机相关的驱动。


cd Desktop\lerobot
pip install -e ".[feetech]" -i https://pypi.tuna.tsinghua.edu.cn/simple

(2) Ubuntu配置虚拟环境

①创建虚拟环境

Ctrl+Alt+T打开终端，输入指令，按下Enter，创建虚拟环境并安装ffmpeg包（建议7.1.1，支持 libsvtav1编码）。


conda create -n lerobot python=3.20.18 ffmpeg=7.1.1 -c conda-forge
出现下图标志，按y，再按Enter继续。


创建完成之后，输入指令，即可查到所创建的虚拟环境。


conda env list

②进入虚拟环境


conda activate lerobot

③下载代码库

LeRobot SO-101机械臂工程包路径：软件工具&源码程序\源码程序\lerobot.zip

将LeRobot SO-101机械臂工程包拷到ubuntu系统上放到/home/ubuntu下，使用unzip工具进行解压，输入指令，进行解压。


unzip lerobot.zip

终端输入指令查看文件。


ls

④安装依赖包

进入到lerobot目录，安装lerobot的依赖包并且指定添加飞特舵机相关的驱动。


cd lerobot
pip install -e ".[feetech]" -i https://pypi.tuna.tsinghua.edu.cn/simple

3. 机械臂组装
后续步骤ubuntu系统和windows系统操作相同，这里以windows为例。

NOTE

在ubuntu系统 上，可能需要通过运行以下命令来授予对 USB 端口的访问权限：

sudo chmod 666 /dev/ttyACM0sudo chmod 666 /dev/ttyACM1

3.1 舵机ID设置（选看）
本小节适用于DIY散件用户，成品用户只需了解即可。

机械臂从上往下的每个舵机的命名依次为：gripper、wrist_roll、wrist_flex、elbow_flex、shoulder_lift和shoulder_pan，分别对应着ID6到ID1。


NOTE

在设置舵机ID时，只能有一个舵机连接主控板，其它串联的信号线都需要拔掉。

3.1.1 从机械臂（跟随者）
win+R打开控制面板，输入cmd，打开终端。


输入指令，进入虚拟环境。


conda activate lerobot

使用cd工具跳到工程文件夹下，输入指令，进行ID设置。


cd Desktop\lerobot
lerobot-setup-motors --robot.type=so101_follower --robot.port=COM24

每出现一个舵机名提示，要确保单独插入了对应ID舵机，然后回车即可自动设置。当出现下一个舵机名称提示，代表上一个舵机设置完成，后续插拔重复回车操作即可。

NOTE

注意要标记好设置的ID号，不要搞混了，对应ID号装到对应关节上。


3.2 硬件组装
查看相关视频，路径：1.课程资料\视频教程\3.2硬件组装

3.3 相机安装
查看相关视频，路径：1.课程资料\视频教程\3.3 相机安装教程

3.4 电路连接
查看相关视频，路径：1.课程资料\视频教程\3.4 电路连接教程

3.5 查找端口号
可先插入从臂，打开设备管理器，查看端口号。

再插入主臂，查看新增的端口号。

为了后续更方便使用，可以设置固定端口号。右键COM图标，点属性，点击端口设置->高级。

点击端口号选择主臂端口号设置为COM22，从臂端口号设置为COM24，由于我之前已经设置过，COM22有使用中的标志，则说明端口被占用。

主臂和从臂端口号分别设置为22和24，设置好后，如下图所示即为成功。

3.1.2 主机械臂（领导者）
输入指令，进行ID设置。


lerobot-setup-motors --teleop.type=so101_leader --teleop.port=COM22
步骤同从机械臂。

4. 机械臂控制
4.1 校准
NOTE

购买成品无需进行校准，可直接跳过。

接下来，需要校准机器人，以确保主机械臂和从机械臂在处于相同物理位置时具有相同的位置值。

4.1.1 从机械臂（跟随者）
输入指令，进行校准。


lerobot-calibrate --robot.type=so101_follower --robot.port=COM24 --robot.id=my_awesome_follower_arm

需要将机器人所有关节都移动到机械臂初始位置，如下图所示。


如果没有校准过，按下Enter即可进入校准，校准过需要重新校准的，需要输入c，再按Enter，才能进行重新校准。


校准通过手动掰动机械臂每个关节进行校准，具体的看查看视频进行了解。

4.1.2 主机械臂（领导者）
输入指令，进行校准。


lerobot-calibrate --teleop.type=so101_leader --teleop.port=COM22 --teleop.id=my_awesome_leader_arm
步骤同从机械臂。

4.2 遥操作不带视觉
输入指令，进行机械臂控制。


python -m lerobot.teleoperate --robot.type=so101_follower --robot.port=COM24 --robot.id=my_awesome_follower_arm --teleop.type=so101_leader --teleop.port=COM22 --teleop.id=my_awesome_leader_arm

当出现下图提示时，按下Enter继续。


出现下图界面，即可通过主机械臂遥控从机械臂。


按下Ctrl+c即可终止终止程序。

4.3 遥操作带视觉
将两个摄像头的USB插到电脑上。

NOTE

①如果使用拓展坞，两个摄像头的USB不能都接在拓展坞上。

②固定环境摄像头的画面必须能够看到整个从机械臂的动作。

输入指令，查找摄像头ID，检查是否有两个摄像头的画面。


lerobot-find-cameras opencv

运行结束，会将捕获的图片保存到outputs\captured_images。


可以通过文件名来区分摄像头的ID，opencv_0对应着index_or_path：0，opencv_1对应着index_or_path：1。

运行指令，进行遥控机械臂可视化。


python -m lerobot.teleoperate --robot.type=so101_follower --robot.port=COM24 --robot.id=my_awesome_follower_arm --robot.cameras="{ fixed: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}, handeye: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}}" --teleop.type=so101_leader --teleop.port=COM22 --teleop.id=my_awesome_leader_arm --display_data=true

NOTE

fixed为固定环境摄像头，handeye为夹爪相机。

出现下面提示词，按Enter继续。


通过主机械臂控制从机械臂的同时会回传摄像头捕捉到的画面。若想关闭程序，在终端中Ctrl+c即可关闭。


5. 数据采集
数据采集步骤：

初始化机器人和传感器。
启动遥操作界面。
操作者控制机器人完成任务。
系统同步记录所有传感器数据和控制指令。
数据被保存为标准 LeRobot 数据集格式。
可选的实时质量监控和可视化。
NOTE

数据采集工作，需要熟练控制机械臂进行夹取方可进行操作，以免操作不规范导致数据不精准。

运行指令，进行数据采集，${HF_USER}可以改为自己用户名（注意用户名必须为英文）。这里的指令我们以采集20次为例，如果需要采集更多次，需要将dataset.num_episodes=20这个20改为更多次数。


python -m lerobot.record --robot.type=so101_follower --robot.port=COM24 --robot.id=my_awesome_follower_arm --robot.cameras="{ handeye: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}, front: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}}" --teleop.type=so101_leader --teleop.port=COM22 --teleop.id=my_awesome_leader_arm --display_data=true --dataset.repo_id=${HF_USER}/demo --dataset.num_episodes=20 --dataset.single_task="Grab the screwdriver"

出现下图提示，按下Enter继续。


出现下图提示，则说明已经进入数据录制，这时可以操控主机械臂来控制从机械臂进行目标物体夹取，放置目标位置。


NOTE

录制的时候，除了机械臂，环境最好相对静止，这样的效果最好，例如：摄像头捕捉到的画面最好只要机械臂在运动，手臂、人等最好不要出现在画面里。

动作执行完毕后，按下**→**继续，出现下图提示则可以将环境进行复位。


环境复位完毕后，按下**→进行保存数据，当出现下图所示的进度条加载到100%则说明数据保存完毕。如果不想要当前轮的数据按←**即可进行重新录制，本轮数据将不会保存。


上一轮录制结束，等待下一次录制的标志，如下图所示，则说明已经进入下一轮数据录制。


这里采集20轮数据为例，为了数据多样性，每轮目标物体放置的位置最好不要相同。


当到Recording episode 19，则说明已进入第二十轮录制，录制完后会后打印Stop recording，说明已录制完毕，按下Esc终止程序就行。


数据默认保存到C:\Users\Admin\.cache\huggingface\lerobot中。


6. 数据集训练
6.1 云服务器训练
6.1.1 云主机租用
本次课程所选用的云主机平台为智星云。

智星云 AI Galaxy | GPU云服务器 GPU服务器租用 远程GPU租用 深度学习服务器 | 免费GPU 便宜GPU

如下图所示，右上角进行登录，没注册过的需要注册一下。


在算力市场中根据需求选择相对应的GPU云主机，本课程所采用的主机为RTX4090，训练时长大致约两个小时，配置如下。

NOTE

RTX4090 1GPU 8核16G 系统200G

镜像22.04带cuda12.4，宽带应该选80左右

选择好系统镜像，点击立即租用。


选择你的计费方式，根据自己需求进行选择，此次数据集训练大概需要3个小时，建议租用结束后保留全部磁盘，防止数据丢失，勾选好后，点击创建实例。


点击控制台即可看到你所创建的实例。


6.1.2 连接方式查看
点击查看连接方式，选择ssh连接，即可看到地址、账户、端口和密码。


6.1.3 数据集上传
使用MobaXterm进行文件传输，打开MobaXterm后，点击Session。

MobaXterm远程连接软件下载路径：软件工具&源码程序\软件工具\MobaXterm_Installer_v22.1.zip


使用SFTP进行文件传输，将租用云主机的地址、用户名和端口进行填写，如下图所示，然后点击OK。


输入云主机的密码，进行登录。


打开文件夹，找到采集的数据，这里存放的路径为C:\Users\Admin\.cache\huggingface\lerobot\Admin，将demo文件夹整个拖到云主机上。


传输完成后，可查看root目录下是否有一个demo文件夹。


6.1.4 lerobot工程包上传
将lerobot.zip文件拖到云主机上。


传输完成后，可查看root目录下是否有一个lerobot.zip文件。

6.1.5 数据集训练
点击复制SSH登录命令。


win+R打开控制面板，输入cmd，打开终端。


将指令复制到终端中，点击Enter，输入yes后点击Enter。


输入云主机密码。


下图所示则为登录成功。


使用apt工具下载screen。


apt install -y screen

使用unzip工具解压lerobot.zip文件。


unzip lerobot.zip

使用Miniconda创建虚拟环境并安装ffmpeg。


conda create -n lerobot python=3.20.18 ffmpeg=7.1.1 -c conda-forge

出现下图所示的提示，则说明创建成功。


激活虚拟环境。


conda activate lerobot

使用cd工具，跳转到lerobot目录下，安装lerobot的依赖包并且指定添加飞特舵机相关的驱动。


cd lerobot
pip install -e ".[feetech]" -i https://pypi.tuna.tsinghua.edu.cn/simple

输入指令，创建数据集存储路径。


mkdir -p /root/.cache/huggingface/lerobot/

将/root/demo移到 /root/.cache/huggingface/lerobot下。


mv /root/demo/ /root/.cache/huggingface/lerobot/

创建一个名为lerobot的session，如需退出session，Ctrl+a+d即可退出session（screen是一个终端复用器，它允许你在一个终端窗口中创建多个虚拟终端会话）。


screen -S lerobot

输入指令，即可进入session。


screen -r lerobot
激活虚拟环境。


conda activate lerobot

使用cd指令进行跳转目录，输入指令，跳转到~/lerobot/src下。


输入指令，进行训练。


python lerobot/scripts/train.py --dataset.repo_id=demo --policy.type=act --output_dir=outputs/train/act_so101_test --job_name=act_so101_test --policy.device=cuda --wandb.enable=false  --policy.push_to_hub=false

训练完，将在lerobot/outputs生成一个train的文件夹，具体路径为/root/lerobot/outputs/train。


继续使用SFTP，将训练好的文件传输到本机上的工程文件下，路径为：lerobot\outputs。


至此就完成训练步骤了，接下来就可以推理测试了。

6.2 本机训练
数据集默认保存到C:\Users\Admin\.cache\huggingface\lerobot中。


win+X点击终端管理员，以管理员权限打开命令行终端。


输入指令，激活虚拟环境并跳到lerobot工作目录下。


conda activate lerobot
cd .\Desktop\lerobot\

NOTE

没有独显的电脑不推荐在本机上训练。

下面的步骤需要电脑独显方可操作。

输入指令，安装cuda11.8。


pip install torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu118

模型训练的参数配置文件在src\lerobot\configs\train.py里，如下图所示，根据需求自行调整模型训练的配置。


参数说明：

dataset: 数据集配置对象，定义训练使用的数据集

env: 环境配置对象，用于定义机器人仿真或真实环境的参数（可选）

policy: 预训练模型配置，定义策略网络的架构和参数（可选）

output_dir: 训练输出目录路径，存储模型检查点、日志等文件。若使用相同路径再次训练会覆盖内容（除非启用 resume）

job_name: 任务名称，用于标识当前训练任务（可选）

resume: 是否从检查点恢复训练。设为 True 时需确保 output_dir 中存在至少一个检查点文件

seed: 随机种子（默认 1000），用于控制模型初始化、数据集打乱和评估环境的随机性，确保实验可复现

num_workers: 数据加载器的工作进程数（默认 4），影响数据加载速度

batch_size: 批次大小（默认 8），每次迭代处理的样本数量

steps: 总训练步数（默认 100,000）

eval_freq: 评估频率（默认每 20,000 步），定期在验证集上评估模型性能

log_freq: 日志记录频率（默认每 200 步），控制训练指标的记录间隔

save_checkpoint: 是否保存训练检查点（默认 True）

save_freq: 检查点保存频率（默认每 20,000 步），最后一步训练后也会保存

use_policy_training_preset: 是否使用策略训练预设配置（默认 True）

optimizer: 优化器配置对象，定义学习率、权重衰减等参数（可选）

scheduler: 学习率调度器配置，定义学习率衰减策略（可选）

eval: 评估配置对象，包含评估相关的详细设置

wandb: Weights & Biases 配置对象，用于实验跟踪和可视化

输入指令，进行训练。


python src/lerobot/scripts/train.py --dataset.repo_id=${HF_USER}/demo --policy.type=act --output_dir=outputs/train/act_so101_test --job_name=act_so101_test --policy.device=cuda --wandb.enable=false  --policy.push_to_hub=false

训练完，将在lerobot/outputs生成一个train的文件夹，具体路径为C:/Users/Admin/Desktop/lerobot/outputs/train。


7. 模型测试
SO-ARM101开源6轴机械臂推理是通过数据驱动的方式，让机器人模仿人类行为。它将复杂的机器人控制问题视为一个监督学习任务，其推理过程依赖于训练好的模型，该模型能够将从环境（主要是视觉观察）和自然语言指令中提取的信息进行多模态融合，并直接映射为控制机器人的具体动作。本质上，这是一种基于“行为克隆”的模仿学习，旨在让机器人通过学习人类演示数据，获得从感知到行动的端到端推理能力，从而完成特定任务。

推理部署步骤：

加载训练好的策略模型。
初始化物理机器人及其传感器。
建立传感器数据到策略输入的映射。
建立策略输出到机器人控制指令的映射。
在控制循环中执行策略推理和机器人控制。
可选的实时可视化和监控。
7.1 实时推理测试
win+R打开控制面板，输入cmd，打开终端。


输入指令，进入虚拟环境并进入到工程目录下。


conda activate lerobot
cd Desktop\lerobot

输入指令，进行推理。

NOTE

outputs/train/act_so101_test/checkpoints/100000/pretrained_model这里的100000为你设置的steps参数（总训练步数）。


python -m lerobot.record --robot.type=so101_follower --robot.port=COM24 --robot.id=my_awesome_follower_arm --robot.cameras="{ handeye: {type: opencv, index_or_path: 0, width: 640, height: 480, fps: 30}, front: {type: opencv, index_or_path: 1, width: 640, height: 480, fps: 30}}" --display_data=true --dataset.repo_id=${HF_USER}/eval_so101 --dataset.single_task="Grab the screwdriver" --policy.path=outputs/train/act_so101_test/checkpoints/100000/pretrained_model
当出现下图提示，按下Enter继续。


当出现下图标志，则说明机械臂开始推理。


出现下图标志，则说明机械臂推理结束。


按下**→**进入下一轮推理。

7.2 推理时常见问题
问题1：分布偏移与泛化能力差

​ 问题描述：模型在训练时见过的状态（如物体位置、光照、背景）下表现良好，但一旦遇到与训练数据稍有不同的情况（即“分布外”数据），性能就会急剧下降。例如，训练时是白色桌子，推理时换成木纹桌子，机器人可能就无法识别物体了。

​ 根本原因：模型学习到的是训练数据中状态的静态分布，而非对物理世界的深层理解。它是在“记忆”而非真正“理解”任务。

问题2：复合误差

​ 问题描述：这是行为克隆最经典的问题。在推理的每一步，模型都会产生微小的动作误差。由于是开环执行（没有根据结果实时修正），下一步的输入状态已经是上一个错误动作导致的结果，这与训练数据中的理想状态越来越远。误差会一步步累积，最终导致机器人完全偏离正确轨迹，任务失败。

​ 根本原因：推理过程中存在误差，当误差一直在累积的话，就会逐渐偏离原本的轨道。

问题3：对演示风格的过度拟合

​ 问题描述：模型可能不仅学习了完成任务所需的必要动作，还学习了演示者的个人习惯或特定风格（如一种奇怪的、低效的抓取姿势）。当环境变化时，这种僵化的风格可能不再有效。

​ 根本原因：模型的目标是最大限度地模仿演示数据，而演示数据中可能包含非最优或与任务无关的行为模式。

Pager
Previous page
附录
