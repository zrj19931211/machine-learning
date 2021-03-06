from zhongrj.model.BaseModel import *
from zhongrj.reference.spatial_transformer_network import spatial_transformer_network as stn

"""
    总结和问题：
        1. spatial_transformer_network是怎么产生gradient的?
        2. theta的初始值很重要[[1, 0, 0], [0, 1, 0]]
        3. batch_normalization Test的时候 training设为False
"""


class STN_CNN(BaseModel):
    def __init__(self,
                 name,
                 x_dims,
                 y_classes,
                 stn_cnn_units,
                 stn_dnn_units,
                 classifier_cnn_units,
                 classifier_dnn_units,
                 learning_rate,
                 trans_dims=None,
                 batch=50,
                 limit_rotate=False):
        BaseModel.__init__(self, name, batch)

        self.x_width, self.x_height, self.x_channel = x_dims
        self.y_classes = y_classes

        self.stn_cnn_units = stn_cnn_units
        self.stn_dnn_units = stn_dnn_units
        self.classifier_cnn_units = classifier_cnn_units
        self.classifier_dnn_units = classifier_dnn_units

        self.learning_rate = learning_rate
        if trans_dims is None:
            trans_dims = x_dims
        self.trans_width, self.trans_height, self.trans_channel = trans_dims
        self.limit_rotate = limit_rotate

        self.__build()
        self._init_sess(graph=False)

    def __build(self):
        with tf.name_scope('inputs'):
            self.x = tf.placeholder(tf.float32, [None, self.x_width * self.x_height * self.x_channel])
            self.y_actual = tf.placeholder(tf.float32, [None, self.y_classes])
            self.is_train = tf.placeholder(tf.bool, name='is_train')
        self.x_image = tf.reshape(self.x, [-1, self.x_height, self.x_width, self.x_channel])
        self.__build_stn()
        self.__build_cnn()
        self.__def_optimizer()

    def __build_stn(self):
        print('Building STN ...')
        self.theta = STN(self.x_image,
                         [[self.trans_width / self.x_width, 0, 0],
                          [0, self.trans_height / self.x_height, 0]],
                         name='STN',
                         limit_rotate=self.limit_rotate,
                         cnn_units=self.stn_cnn_units,
                         dnn_units=self.stn_dnn_units,
                         batch_noraml=True,
                         is_train=self.is_train)
        with tf.variable_scope('Transformer'):
            self.x_image_trans = tf.reshape(stn(self.x_image, self.theta, [self.trans_height, self.trans_width]),
                                            [-1, self.trans_height, self.trans_width, self.trans_channel])
        [print(param) for param in tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, 'STN')]

    def __build_cnn(self):
        print('Building CNN ...')
        self.y_predict = CNN(self.x_image_trans,
                             self.y_classes,
                             name='CNN',
                             cnn_units=self.classifier_cnn_units,
                             dnn_units=self.classifier_dnn_units,
                             batch_noraml=True,
                             is_train=self.is_train)
        [print(param) for param in tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES, 'CNN')]

    def __def_optimizer(self):
        with tf.name_scope('loss'):
            self.loss = softmax_cross_entropy_mean(logits=self.y_predict, labels=self.y_actual)
        with tf.control_dependencies(tf.get_collection(tf.GraphKeys.UPDATE_OPS)), tf.name_scope('optimizer'):
            self.optimizer = tf.train.AdamOptimizer(self.learning_rate).minimize(self.loss, self.global_step)
        with tf.name_scope('accuracy'):
            correct_pred = tf.equal(tf.argmax(self.y_predict, 1), tf.argmax(self.y_actual, 1))
            self.accuracy = tf.reduce_mean(tf.cast(correct_pred, tf.float32))

    # 这个方法搞得我差点死掉...
    def __draw_detected(self, images, thetas):
        color = 1 if self.x_channel == 1 else (255, 0, 0)

        def center_affine(theta, x, y):
            x_ = x - self.x_width / 2
            y_ = y - self.x_height / 2
            return (np.sum(theta.reshape([2, 3]) * np.array([[x_, y_, self.x_width / 2],
                                                             [x_, y_, self.x_height / 2]]),
                           axis=1).squeeze() + np.array([self.x_width / 2, self.x_height / 2])).astype(np.int)

        return [draw_surround(
            images[i],
            center_affine(thetas[i], 0, 0) + np.array([-1, -1]),
            center_affine(thetas[i], 0, self.x_height) + np.array([-1, 1]),
            center_affine(thetas[i], self.x_width, self.x_height) + np.array([1, 1]),
            center_affine(thetas[i], self.x_width, 0) + np.array([1, -1]),
            color=color
        ).reshape([self.x_height, self.x_width, self.x_channel]) for i in range(len(images))]

    def __generate_image(self, name, feed_dict):
        image_, theta_, image_trans_, predict_ = self.sess.run(
            [self.x_image, self.theta, self.x_image_trans, self.y_predict], feed_dict)
        save_image(
            # [im for im in image_[:10]] +
            self.__draw_detected(image_[:24], theta_[:24]) +
            [im for im in image_trans_[:24]],
            name=self.output_dir + name,
            n_each_row=8,
            text=predict_[:24].argmax(axis=1)
        )

    def train(self, images, labels):
        print('Training ...')
        one_epoch_step = len(images) // self.batch
        print('one_epoch_step: ', one_epoch_step)
        images = images.reshape([-1, self.x_width * self.x_height * self.x_channel])
        labels = labels.reshape([-1, self.y_classes])
        sample_feed_dict = {
            self.x: images[self.sess.run(self.sample)],
            self.is_train: True
        }
        while True:
            batch_mask = np.random.choice(len(images), self.batch)
            batch = images[batch_mask], labels[batch_mask]
            feed_dict = {
                self.x: batch[0],
                self.y_actual: batch[1],
                self.is_train: True
            }
            _, i_global, accuracy_, loss_ = self.sess.run(
                [self.optimizer, self.global_step, self.accuracy, self.loss], feed_dict)

            if i_global % 10 == 0:
                print('step ', i_global)
                print('accuracy ', accuracy_)
                print('loss ', loss_)

            save_interval = 100
            if i_global % save_interval == 0:
                self.__generate_image('random_{}'.format(i_global // save_interval), feed_dict)
                self.__generate_image('sample_{}'.format(i_global // save_interval), sample_feed_dict)
            if i_global % 500 == 0:
                self.save_sess()

    def test(self, images, labels):
        print('Test ...')
        images = images.reshape([-1, self.x_width * self.x_height * self.x_channel])
        labels = labels.reshape([-1, self.y_classes])
        test_mask = np.random.choice(len(images), 100)
        feed_dict = {
            self.x: images[test_mask],
            self.y_actual: labels[test_mask],
            self.is_train: False
        }
        accuracy = self.sess.run(self.accuracy, feed_dict)
        print('accuracy ', accuracy)
        for i in range(10):
            feed_dict = {
                self.x: images[np.random.choice(len(images), 50)],
                self.is_train: False
            }
            self.__generate_image('test_{}'.format(i), feed_dict)


MODE = 'train'


def mnist_distortions():
    """扭曲数字识别"""
    from zhongrj.data.mnist_distortions import load_data

    model = STN_CNN(
        name='STN_CNN_mnist_distortions',
        x_dims=[40, 40, 1],
        trans_dims=[15, 20, 1],
        y_classes=10,
        stn_cnn_units=[16, 32],
        stn_dnn_units=[1024, 256],
        classifier_cnn_units=[16, 32],
        classifier_dnn_units=[512, 128],
        learning_rate=1e-3,
        batch=50
    )

    print('Loading Data ...')
    data = load_data()

    if MODE == 'train':
        model.train(data['train_x'], data['train_y'])
    elif MODE == 'test':
        model.test(data['test_x'], data['test_y'])


def catvsdog():
    """猫狗大战"""
    from zhongrj.data.catvsdog import load_data

    model = STN_CNN(
        name='STN_CNN_catvsdog',
        x_dims=[150, 150, 3],
        trans_dims=[60, 60, 3],
        y_classes=2,
        stn_cnn_units=[20, 20, 20],
        stn_dnn_units=[1000, 200],
        classifier_cnn_units=[10, 10, 10],
        classifier_dnn_units=[400, 200],
        learning_rate=5e-4,
        batch=50,
    )

    print('Loading Data ...')
    data = load_data()

    if MODE == 'train':
        model.train(data['train_x'], data['train_y'])
    elif MODE == 'test':
        model.test(data['test_x'], data['test_y'])


if __name__ == '__main__':
    catvsdog()
